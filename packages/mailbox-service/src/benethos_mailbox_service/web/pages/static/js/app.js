// The configuration UI's own script. The pages work without it; it adds a
// confirmation before destructive forms. No inline handlers: the content
// security policy allows scripts from this origin only.
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
