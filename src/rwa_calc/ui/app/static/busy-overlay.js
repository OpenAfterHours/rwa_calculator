/* Phase A — indeterminate busy overlay for blocking form posts.
 *
 * Loaded on every page (base.html) but only acts on a <form data-busy-overlay>.
 * On submit it paints a full-screen overlay with a spinner and a live elapsed
 * timer, then lets the normal navigation proceed; the server's response page
 * replaces the overlay when it arrives. Deliberately makes no completion claim
 * — an honest "working" signal, not a fake progress bar.
 *
 * The calculator form does NOT use this: it gets the real stage stepper via the
 * /calculating page (calculating.js).
 */
(function () {
  "use strict";

  function fmtElapsed(totalSeconds) {
    var m = Math.floor(totalSeconds / 60);
    var s = totalSeconds % 60;
    return m + ":" + (s < 10 ? "0" : "") + s + " elapsed";
  }

  function showOverlay(message) {
    if (document.querySelector(".calc-overlay")) return;

    var overlay = document.createElement("div");
    overlay.className = "calc-overlay";
    overlay.setAttribute("role", "status");
    overlay.setAttribute("aria-live", "polite");

    var card = document.createElement("div");
    card.className = "calc-overlay__card";

    var spinner = document.createElement("div");
    spinner.className = "spinner";

    var msg = document.createElement("div");
    msg.className = "calc-overlay__msg";
    msg.textContent = message;

    var elapsed = document.createElement("div");
    elapsed.className = "calc-overlay__elapsed mono";
    elapsed.textContent = fmtElapsed(0);

    var hint = document.createElement("div");
    hint.className = "calc-overlay__hint muted";
    hint.textContent = "Running locally — please keep this tab open.";

    card.appendChild(spinner);
    card.appendChild(msg);
    card.appendChild(elapsed);
    card.appendChild(hint);
    overlay.appendChild(card);
    document.body.appendChild(overlay);

    var start = Date.now();
    setInterval(function () {
      elapsed.textContent = fmtElapsed(Math.floor((Date.now() - start) / 1000));
    }, 1000);
  }

  // Capture-phase listener: an invalid form never fires `submit` (the browser
  // shows native validation instead), so the overlay only appears on a real
  // submission.
  document.addEventListener(
    "submit",
    function (event) {
      var form = event.target;
      if (!(form instanceof HTMLFormElement)) return;
      if (!form.hasAttribute("data-busy-overlay")) return;
      showOverlay(form.getAttribute("data-busy-overlay") || "Working…");
    },
    true
  );
})();
