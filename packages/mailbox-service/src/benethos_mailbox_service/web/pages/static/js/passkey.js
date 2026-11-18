// Passkeys (docs/AUTHENTICATION.md 4, 5). The browser makes and signs
// them, this script carries its answer into the form that asked.
//
// A <button data-passkey-use="options"> signs the challenge of its
// options with one of the person's passkeys, puts the answer in the
// hidden field "passkey" of its form and sends the form. A code field
// marked data-passkey-instead is not needed then.
// A <button data-passkey-create="options"> makes a new passkey and sends
// its answer in the hidden field "answer".
// Both stay hidden where the browser has no passkeys, and an element
// data-passkey-missing shows instead. Without this script a form takes a
// code alone.
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

function say(form, text) {
  const status = form.querySelector("[data-passkey-status]");
  if (status) status.textContent = text;
}

async function use(button) {
  const form = button.form;
  const instead = [...form.querySelectorAll("[data-passkey-instead]")];
  for (const field of instead) field.required = false;
  if (!form.reportValidity()) {
    for (const field of instead) field.required = true;
    return;
  }
  const options = request(JSON.parse(button.dataset.passkeyUse));
  const credential = await navigator.credentials.get({ publicKey: options });
  form.elements.passkey.value = answerOf(credential);
  for (const field of instead) field.value = "";
  form.requestSubmit();
}

async function create(button) {
  const form = button.form;
  const options = creation(JSON.parse(button.dataset.passkeyCreate));
  const credential = await navigator.credentials.create({ publicKey: options });
  form.elements.answer.value = answerOf(credential);
  form.requestSubmit();
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-passkey-use], [data-passkey-create]");
  if (!button || !button.form) return;
  event.preventDefault();
  say(button.form, "");
  const asked = button.dataset.passkeyCreate ? create(button) : use(button);
  asked.catch((error) => {
    // NotAllowedError: the person cancelled, or the time ran out.
    say(
      button.form,
      error && error.name === "NotAllowedError"
        ? "No passkey was used. Try again, or use a code."
        : "The browser made no passkey: " + (error && error.message),
    );
  });
});

function reveal() {
  const works = "PublicKeyCredential" in window && navigator.credentials;
  const shown = works ? "[data-passkey-use], [data-passkey-create]" : "[data-passkey-missing]";
  for (const element of document.querySelectorAll(shown)) element.hidden = false;
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", reveal);
} else {
  reveal();
}
