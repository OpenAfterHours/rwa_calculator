/* Fit the report grid's scroll pane to the viewport.

   The pane (`.grid-wrap`) is the last element on the templates page: sizing it
   to the space below its top edge keeps its own horizontal scrollbar on screen
   — on a 49-column return that scrollbar IS the affordance that more columns
   exist. The stylesheet carries a static fallback (`max-height:
   calc(100dvh - 300px)`); this trues it up to the real remainder, whatever the
   header chrome above the grid actually takes. `max-height` (not `height`) so
   short templates stay short. */
(function () {
  "use strict";

  var MIN_PANE_PX = 320;
  /* Clears what follows the pane — the grid card's 16px bottom margin plus the
     container's 24px bottom padding — so the fitted page needs no scrollbar. */
  var BOTTOM_MARGIN_PX = 44;

  function fit() {
    var wrap = document.querySelector(".grid-wrap");
    if (!wrap) {
      return;
    }
    var top = wrap.getBoundingClientRect().top;
    var height = Math.max(MIN_PANE_PX, window.innerHeight - top - BOTTOM_MARGIN_PX);
    wrap.style.maxHeight = height + "px";
  }

  window.addEventListener("resize", fit);
  window.addEventListener("load", fit); /* re-fit once fonts have settled */
  fit();
})();
