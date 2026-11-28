// Keep ordinary link navigation, including keyboard use, history and opening another tab.
(() => {
  const status = document.querySelector(".cell-loading");
  const panel = document.querySelector(".cell-panel");
  let timer;
  let pendingCell;

  function clear() {
    clearTimeout(timer);
    status.textContent = "";
    panel.removeAttribute("aria-busy");
    panel.inert = false;
    pendingCell?.classList.remove("cell-pending");
  }

  function pending(href, source) {
    clear();
    const url = new URL(href);
    const row = url.searchParams.get("row");
    const col = url.searchParams.get("col");
    if (url.origin !== location.origin || url.pathname !== location.pathname || !row || !col) return;
    timer = setTimeout(() => {
      pendingCell = source?.closest(".grid td");
      pendingCell?.classList.add("cell-pending");
      panel.inert = true;
      panel.setAttribute("aria-busy", "true");
      status.textContent = `Loading breakdown for row ${row}, column ${col}…`;
    }, 200);
  }

  if (window.navigation) {
    window.navigation.addEventListener("navigate", (event) => {
      if (event.hashChange || event.downloadRequest != null) return;
      pending(event.destination.url, event.sourceElement);
      event.signal.addEventListener("abort", clear, { once: true });
    });
  } else {
    document.addEventListener("click", (event) => {
      if (event.defaultPrevented || event.button !== 0 || event.ctrlKey ||
          event.metaKey || event.shiftKey || event.altKey) return;
      const link = event.target.closest("a[href]");
      if (!link || link.target || link.hasAttribute("download")) return;
      if (link.matches(".grid td a, .breakdown nav a")) pending(link.href, link);
      else clear();
    });
  }
  window.addEventListener("keydown", (event) => { if (event.key === "Escape") clear(); });
  window.addEventListener("pagehide", clear);
  window.addEventListener("pageshow", clear);
})();
