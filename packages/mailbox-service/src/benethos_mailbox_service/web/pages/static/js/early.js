// Runs before the page is drawn. It marks that the script runs, so the
// forms at a row fold until opened (without it they show at once), and
// keeps a folded sidebar folded on every page. The fold is the viewer's
// own choice, kept in this browser: nothing breaks without it.
"use strict";

document.documentElement.classList.add("js");
try {
  if (window.localStorage.getItem("mailbox.sidebar") === "folded") {
    document.documentElement.classList.add("nav-folded");
  }
} catch {
  // Storage blocked: the sidebar stays open.
}
