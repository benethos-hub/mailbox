// The configuration UI's own script. The pages work without it; it adds a
// confirmation before destructive forms and opens forms htmx loads into
// #modal as a dialog. No inline handlers: the content security policy
// allows scripts from this origin only.
"use strict";

// <form data-confirm="Delete this?"> asks before it is sent; so does a
// <button data-confirm="..."> for the submit it makes.
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  const question = event.submitter?.dataset.confirm || form.dataset.confirm;
  if (question && !window.confirm(question)) {
    event.preventDefault();
  }
});

// A <dialog> htmx swapped into #modal opens at once; closing it empties the
// container, so the next form starts fresh.
document.addEventListener("htmx:afterSwap", (event) => {
  const target = event.detail.target;
  if (!target || target.id !== "modal") return;
  const dialog = target.querySelector("dialog");
  if (!dialog) return;
  dialog.addEventListener("close", () => { target.innerHTML = ""; });
  dialog.showModal();
});

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-close]");
  if (button) button.closest("dialog")?.close();
});
