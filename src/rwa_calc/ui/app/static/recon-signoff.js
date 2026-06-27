/* Inline sign-off for the per-key explorer — accept a row without a full reload.
 *
 * Loaded only on the explorer page (recon_explorer.html). On the default Open
 * worklist, intercepting a <form class="inline-signoff"> submit and POSTing it in
 * the background lets the analyst run down the list ticking items off: the actioned
 * row is dropped from the table and the burndown counters update in place, so the
 * scroll position is kept (a full reload would jump back to the top).
 *
 * Progressive enhancement: with JS disabled, or on any non-Open view, or if the
 * fetch fails, the form posts normally (303 -> full reload) — the action still
 * happens, this just removes the page jump.
 */
(function () {
  "use strict";

  function isOpenView() {
    var el = document.querySelector("[data-signoff-status]");
    return !!el && el.getAttribute("data-signoff-status") === "open";
  }

  function updateProgress(progress) {
    if (!progress) return;
    ["reviewed", "open", "accepted", "rejected", "changed", "total"].forEach(function (key) {
      var span = document.querySelector('[data-signoff="' + key + '"]');
      if (span && typeof progress[key] === "number") {
        span.textContent = progress[key].toLocaleString();
      }
    });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    // Destructive "clear all sign-offs" — confirm before letting it through.
    if (form.classList.contains("clear-all-signoff")) {
      if (!window.confirm(form.getAttribute("data-confirm") || "Clear all sign-offs?")) {
        event.preventDefault();
      }
      return;
    }
    if (!form.classList.contains("inline-signoff")) return;
    // Only enhance the Open worklist; other views must stay correct, so let the
    // normal submit (full reload) re-render them.
    if (!isOpenView()) return;

    event.preventDefault();
    var row = form.closest("tr");
    var tbody = row ? row.parentNode : null;
    var button = form.querySelector("button");
    if (button) {
      button.disabled = true;
      button.textContent = "…";
    }

    fetch(form.action, {
      method: "POST",
      headers: { "X-Requested-With": "fetch" },
      body: new FormData(form),
      credentials: "same-origin",
    })
      .then(function (response) {
        if (!response.ok) throw new Error("signoff failed: " + response.status);
        return response.json().catch(function () {
          return null;
        });
      })
      .then(function (data) {
        if (row) row.remove();
        if (data) updateProgress(data.progress);
        // The page just emptied — reload to pull the next page (or the empty state).
        if (tbody && tbody.querySelectorAll("tr").length === 0) {
          window.location.reload();
        }
      })
      .catch(function () {
        // Fall back to a normal submit so the sign-off still lands.
        if (button) {
          button.disabled = false;
          button.textContent = "Accept";
        }
        form.submit();
      });
  });
})();
