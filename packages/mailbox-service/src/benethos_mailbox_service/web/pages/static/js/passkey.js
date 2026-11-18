// The second factor in a form, and passkeys (docs/AUTHENTICATION.md 4,
// 5). The browser makes and signs passkeys, this script carries its
// answer into the form that asked.
//
// An element data-ways holds the methods of the second step, each a
// data-way: "passkey", "totp" or "recovery". One shows at a time, the
// first that works, with its fields on and the others' off. "Try
// another way" (data-ways-other) lists them (data-way-pick). Where the
// passkey shows, sending the form first signs the challenge of its
// data-passkey-options with one of the person's passkeys and puts the
// answer in its hidden field "passkey". data-ways-focus puts the cursor
// in the step when the page opens.
// A <button data-passkey-create="options"> makes a new passkey and sends
// its answer in the hidden field "answer".
// A passkey is offered only where the browser makes passkeys, and an
// element data-passkey-missing shows instead. Without this script the
// first code field shows alone.
"use strict";

// base64url, as WebAuthn writes bytes in JSON, to bytes and back.
function bytesOf(text) {
  const base = text.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base + "===".slice((base.length + 3) % 4);
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0)).buffer;
}

function textOf(buffer) {
  let binary = "";
  for (const byte of new Uint8Array(buffer)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function described(list) {
  return (list || []).map((item) => ({ ...item, id: bytesOf(item.id) }));
}

function creation(options) {
  return {
    ...options,
    challenge: bytesOf(options.challenge),
    user: { ...options.user, id: bytesOf(options.user.id) },
    excludeCredentials: described(options.excludeCredentials),
  };
}

function request(options) {
  return {
    ...options,
    challenge: bytesOf(options.challenge),
    allowCredentials: described(options.allowCredentials),
  };
}

// The credential as the service reads it: the JSON of WebAuthn Level 3.
function answerOf(credential) {
  const found = credential.response;
  const response = { clientDataJSON: textOf(found.clientDataJSON) };
  for (const key of ["attestationObject", "authenticatorData", "signature", "userHandle"]) {
    if (found[key]) response[key] = textOf(found[key]);
  }
  return JSON.stringify({
    id: credential.id,
    rawId: textOf(credential.rawId),
    type: credential.type,
    response,
    clientExtensionResults: credential.getClientExtensionResults(),
  });
}

const works = "PublicKeyCredential" in window && Boolean(navigator.credentials);

// The browser's answer in the form's notice, which shows only with a
// text.
function say(form, text) {
  const status = form.querySelector("[data-passkey-status]");
  if (!status) return;
  status.textContent = text;
  status.hidden = !text;
}

// While the browser asks, the form takes no second click: its buttons
// are locked and the notice says it waits. ``busy`` false frees them.
function waiting(form, buttons, busy) {
  if (busy) {
    form.dataset.passkeyBusy = "";
  } else {
    delete form.dataset.passkeyBusy;
  }
  for (const button of buttons) button.disabled = busy;
  say(form, busy ? "Waiting for your browser…" : "");
}

// The methods of a step this browser can use, in their order.
function usable(step) {
  return [...step.querySelectorAll("[data-way]")].filter(
    (way) => way.dataset.way !== "passkey" || works,
  );
}

function active(step) {
  return step.querySelector("[data-way]:not([hidden])");
}

// The buttons that send the form of the step, locked or free.
function lock(form, locked) {
  for (const button of form?.querySelectorAll("[type=submit]") || []) {
    button.disabled = locked;
  }
}

// Shows the method ``name`` of the step, its fields on, the others off.
// A method shown frees the form's buttons again.
function show(step, name) {
  for (const way of step.querySelectorAll("[data-way]")) {
    const on = way.dataset.way === name;
    way.hidden = !on;
    for (const field of way.querySelectorAll("input")) field.disabled = !on;
  }
  for (const hint of step.querySelectorAll("[data-ways-only]")) hint.hidden = true;
  step.querySelector("[data-ways-choices]").hidden = true;
  const other = step.querySelector("[data-ways-other]");
  other.hidden = usable(step).length < 2;
  other.setAttribute("aria-expanded", "false");
  if (name !== null) lock(step.closest("form"), false);
  say(step.closest("form") || step, "");
}

function focus(step) {
  const way = active(step);
  const field = way && way.querySelector("input:not([type=hidden])");
  const target = field || step.closest("form")?.querySelector("[type=submit]");
  target?.focus();
}

function start(step) {
  const ways = usable(step);
  if (!ways.length) return;
  for (const pick of step.querySelectorAll("[data-way-pick]")) {
    pick.hidden = !ways.some((way) => way.dataset.way === pick.dataset.wayPick);
  }
  show(step, ways[0].dataset.way);
  if ("waysFocus" in step.dataset) focus(step);
}

async function sign(form, way) {
  const buttons = form.querySelectorAll("[type=submit]");
  waiting(form, buttons, true);
  try {
    const options = request(JSON.parse(way.dataset.passkeyOptions));
    const credential = await navigator.credentials.get({ publicKey: options });
    way.querySelector("[name=passkey]").value = answerOf(credential);
  } finally {
    waiting(form, buttons, false);
  }
  form.requestSubmit();
}

async function create(button) {
  const form = button.form;
  waiting(form, [button], true);
  try {
    const options = creation(JSON.parse(button.dataset.passkeyCreate));
    const credential = await navigator.credentials.create({ publicKey: options });
    form.elements.answer.value = answerOf(credential);
  } finally {
    waiting(form, [button], false);
  }
  form.requestSubmit();
}

// NotAllowedError: the person cancelled, or the time ran out.
function failed(form, error, made) {
  const cancelled = error && error.name === "NotAllowedError";
  say(
    form,
    made
      ? cancelled
        ? "No passkey was made. Try again."
        : "The browser made no passkey: " + (error && error.message)
      : cancelled
        ? "The passkey was not used. Try again, or try another way."
        : "The browser used no passkey: " + (error && error.message),
  );
}

// The list of the methods in place of the one shown, its fields off
// and the form's buttons locked until a pick.
function choose(step) {
  show(step, null);
  const other = step.querySelector("[data-ways-other]");
  other.setAttribute("aria-expanded", "true");
  other.hidden = true;
  step.querySelector("[data-ways-choices]").hidden = false;
  lock(step.closest("form"), true);
  step.querySelector("[data-way-pick]:not([hidden])")?.focus();
}

// A form whose step shows the passkey asks for it before it is sent,
// and one whose step lists the methods waits for a pick, also when the
// Enter key sends it. Capturing at the window, the form goes nowhere
// else until then.
window.addEventListener(
  "submit",
  (event) => {
    const form = event.target;
    const choosing = form.querySelector?.("[data-ways-choices]:not([hidden])");
    if (choosing) {
      event.preventDefault();
      event.stopImmediatePropagation();
      choosing.querySelector("[data-way-pick]:not([hidden])")?.focus();
      return;
    }
    const way = form.querySelector?.('[data-way="passkey"]:not([hidden])');
    if (!way || way.querySelector("[name=passkey]").value) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if ("passkeyBusy" in form.dataset) return;
    sign(form, way).catch((error) => failed(form, error, false));
  },
  true,
);

document.addEventListener("click", (event) => {
  const other = event.target.closest?.("[data-ways-other]");
  if (other) {
    choose(other.closest("[data-ways]"));
    return;
  }
  const pick = event.target.closest?.("[data-way-pick]");
  if (pick) {
    const step = pick.closest("[data-ways]");
    show(step, pick.dataset.wayPick);
    const form = step.closest("form");
    // A passkey picked asks for it at once, when nothing else is missing.
    if (pick.dataset.wayPick === "passkey" && form?.checkValidity()) {
      form.requestSubmit();
    } else {
      focus(step);
    }
    return;
  }
  const button = event.target.closest?.("[data-passkey-create]");
  if (!button || !button.form) return;
  event.preventDefault();
  if ("passkeyBusy" in button.form.dataset) return;
  create(button).catch((error) => failed(button.form, error, true));
});

function reveal() {
  const shown = works ? "[data-passkey-create]" : "[data-passkey-missing]";
  for (const element of document.querySelectorAll(shown)) element.hidden = false;
  for (const step of document.querySelectorAll("[data-ways]")) start(step);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", reveal);
} else {
  reveal();
}
