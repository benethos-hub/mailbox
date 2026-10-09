// The configuration UI's own script. The pages work without it; it adds a
// question before forms that change much, copy buttons and a few keys.
// No inline handlers: the content security policy allows scripts from
// this origin only.
"use strict";

// --- the question before a form (docs/UI.md 7) -------------------------------

// <form data-confirm="Delete this? It cannot be undone."> asks before it
// is sent; so does a <button data-confirm="..."> for the submit it makes.
// The text up to the first question mark is the heading, the rest says
// what happens. data-confirm-label names the button, data-confirm-danger
// makes it red.
const asked = new WeakSet();

function ask(source) {
  const dialog = document.getElementById("confirm");
  const question = source.dataset.confirm;
  if (!(dialog instanceof HTMLDialogElement) || !dialog.showModal) {
    return Promise.resolve(window.confirm(question));
  }
  const end = question.indexOf("?");
  const heading = end < 0 ? question : question.slice(0, end + 1);
  document.getElementById("confirm-title").textContent = heading;
  document.getElementById("confirm-text").textContent =
    end < 0 ? "" : question.slice(end + 1).trim();
  const ok = document.getElementById("confirm-ok");
  ok.textContent = source.dataset.confirmLabel || "OK";
  ok.className = source.hasAttribute("data-confirm-danger") ? "danger solid" : "primary";
  dialog.returnValue = "";
  dialog.showModal();
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), {
      once: true,
    });
  });
}

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || form.method === "dialog") return;
  const submitter = event.submitter;
  const source = submitter?.dataset.confirm ? submitter : form;
  if (!source.dataset.confirm) return;
  if (asked.has(form)) {
    asked.delete(form);
    return;
  }
  event.preventDefault();
  ask(source).then((yes) => {
    if (!yes) return;
    asked.add(form);
    form.requestSubmit(submitter && form.contains(submitter) ? submitter : null);
  });
});

// --- copying a secret shown once -----------------------------------------------

function toast(text) {
  const box = document.getElementById("toast");
  if (!box) return;
  box.textContent = text;
  box.hidden = false;
  clearTimeout(box.dataset.timer);
  box.dataset.timer = setTimeout(() => {
    box.hidden = true;
  }, 1800);
}

function select(element) {
  const range = document.createRange();
  range.selectNodeContents(element);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
}

// <button data-copy="id"> copies the text of the element with that id.
// Without the clipboard (a page not on https or localhost) the text is
// selected, to copy with the keyboard.
document.addEventListener("click", (event) => {
  const button = event.target.closest?.("[data-copy]");
  if (!button) return;
  const element = document.getElementById(button.dataset.copy);
  if (!element) return;
  const text = element.innerText.trim();
  if (!navigator.clipboard) {
    select(element);
    toast("Selected: press Ctrl+C to copy");
    return;
  }
  navigator.clipboard.writeText(text).then(
    () => {
      const use = button.querySelector("use");
      const before = use?.getAttribute("href");
      if (use) use.setAttribute("href", before.replace(/#.*/, "#clipboard-check"));
      setTimeout(() => use?.setAttribute("href", before), 1800);
      toast("Copied");
    },
    () => {
      select(element);
      toast("Selected: press Ctrl+C to copy");
    },
  );
});

// --- the account menu and the folded sidebar (docs/UI.md 3) ---------------------

// The menu is a <details>: it opens without a script, and closes here on
// a click elsewhere and on Escape.
function closeMenus(except) {
  for (const menu of document.querySelectorAll("details.account-menu[open]")) {
    if (menu !== except) menu.open = false;
  }
}

document.addEventListener("click", (event) => {
  closeMenus(event.target.closest?.("details.account-menu"));
});

// Folded, the sidebar shows its icons alone: each entry's word becomes its
// tooltip. The choice is kept in this browser only.
function fold(folded) {
  document.documentElement.classList.toggle("nav-folded", folded);
  const button = document.querySelector("[data-fold]");
  if (button) {
    const label = folded ? "Unfold the sidebar" : "Fold the sidebar";
    button.setAttribute("aria-expanded", String(!folded));
    button.title = label;
    button.setAttribute("aria-label", label);
  }
  for (const link of document.querySelectorAll(".nav a")) {
    if (folded) link.title = link.querySelector(".label")?.textContent || "";
    else link.removeAttribute("title");
  }
}

document.addEventListener("click", (event) => {
  if (!event.target.closest?.("[data-fold]")) return;
  const folded = !document.documentElement.classList.contains("nav-folded");
  fold(folded);
  try {
    if (folded) window.localStorage.setItem("mailbox.sidebar", "folded");
    else window.localStorage.removeItem("mailbox.sidebar");
  } catch {
    // Storage blocked: it stays folded on this page only.
  }
});

if (document.documentElement.classList.contains("nav-folded")) fold(true);

// --- keys ------------------------------------------------------------------------

// Escape closes the account menu. The dialog closes by itself.
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  const open = document.querySelector("details.account-menu[open]");
  if (!open) return;
  open.open = false;
  open.querySelector("summary")?.focus();
});

// "/" puts the cursor in the search field of the page, as many sites do.
document.addEventListener("keydown", (event) => {
  if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return;
  const here = document.activeElement;
  if (here && (here.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(here.tagName))) {
    return;
  }
  const search = document.querySelector("form[role=search] input:not([type=hidden])");
  if (!search) return;
  event.preventDefault();
  search.focus();
  search.select();
});
