// Runs before the page is drawn, so a folded sidebar does not open and
// close again on every page. Only the viewer's own choice, kept in this
// browser: nothing breaks without it.
"use strict";

try {
  if (window.localStorage.getItem("mailbox.sidebar") === "folded") {
    document.documentElement.classList.add("nav-folded");
  }
} catch {
  // Storage blocked: the sidebar stays open.
}
