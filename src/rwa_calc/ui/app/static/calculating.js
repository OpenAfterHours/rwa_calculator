/* Phase B — live stage stepper for the /calculating page.
 *
 * Subscribes to /jobs/{id}/events (Server-Sent Events) and ticks each pipeline
 * stage off a fixed checklist as the server reports it complete. Progress is
 * driven off stage ORDER, never a percentage: the spinner honestly parks on the
 * heavy "calculators" step. Falls back to polling /jobs/{id} if EventSource is
 * unavailable or the stream errors. On completion it navigates to the results
 * page (served under the same job id).
 */
(function () {
  "use strict";

  var root = document.getElementById("calc-progress");
  if (!root) return;

  var jobId = root.getAttribute("data-job-id");
  // Where to navigate on success. The calculator stepper points at /results/,
  // the reconciliation stepper at /reconciliation/ — both serve their result
  // under the job id. Defaults to /results/ for backwards safety.
  var resultBase = root.getAttribute("data-result-base") || "/results/";
  var steps = Array.prototype.slice.call(root.querySelectorAll(".step"));
  var byName = {};
  steps.forEach(function (step) {
    byName[step.getAttribute("data-stage")] = step;
  });

  // Live elapsed timer (always truthful, regardless of transport).
  var elapsedEl = document.getElementById("calc-elapsed");
  var start = Date.now();
  var elapsedTimer = setInterval(function () {
    var total = Math.floor((Date.now() - start) / 1000);
    var m = Math.floor(total / 60);
    var s = total % 60;
    elapsedEl.textContent = m + ":" + (s < 10 ? "0" : "") + s + " elapsed";
  }, 1000);

  var terminated = false;

  function markDone(name) {
    var step = byName[name];
    if (step) {
      step.classList.remove("step--active");
      step.classList.add("step--done");
    }
    // The first not-yet-done step becomes the active (spinning) one.
    var next = null;
    for (var i = 0; i < steps.length; i++) {
      if (!steps[i].classList.contains("step--done")) {
        next = steps[i];
        break;
      }
    }
    steps.forEach(function (s) {
      s.classList.remove("step--active");
    });
    if (next) next.classList.add("step--active");
  }

  function finishOk() {
    terminated = true;
    clearInterval(elapsedTimer);
    steps.forEach(function (s) {
      s.classList.remove("step--active");
      s.classList.add("step--done");
    });
    window.location.href = resultBase + jobId;
  }

  function finishError(message) {
    terminated = true;
    clearInterval(elapsedTimer);
    root.classList.add("is-error");
    steps.forEach(function (s) {
      s.classList.remove("step--active");
    });
    var box = document.getElementById("calc-error");
    if (box) {
      box.textContent = message || "Calculation failed — see the server logs.";
      box.style.display = "block";
    }
  }

  function safeParse(text) {
    try {
      return JSON.parse(text);
    } catch (e) {
      return null;
    }
  }

  function startPolling() {
    var poll = setInterval(function () {
      fetch("/jobs/" + jobId, { headers: { Accept: "application/json" } })
        .then(function (r) {
          if (!r.ok) throw new Error("status " + r.status);
          return r.json();
        })
        .then(function (data) {
          (data.completed || []).forEach(markDone);
          if (data.status === "done") {
            clearInterval(poll);
            finishOk();
          } else if (data.status === "error") {
            clearInterval(poll);
            finishError(data.error);
          }
        })
        .catch(function () {
          /* transient — try again on the next tick */
        });
    }, 800);
  }

  if (!window.EventSource) {
    startPolling();
    return;
  }

  var source = new EventSource("/jobs/" + jobId + "/events");

  source.addEventListener("stage", function (event) {
    var data = safeParse(event.data);
    if (data && data.name) markDone(data.name);
  });

  source.addEventListener("done", function () {
    source.close();
    finishOk();
  });

  source.addEventListener("failed", function (event) {
    source.close();
    var data = safeParse(event.data);
    finishError(data && data.error);
  });

  // Native transport error (not a server "failed" event). After a clean close
  // following a terminal event this also fires — guard with `terminated`. Any
  // genuine stream drop falls back to polling, which is reconnect-safe.
  source.onerror = function () {
    if (terminated) return;
    source.close();
    startPolling();
  };
})();
