// A classic script, loaded before main.js, that says so when the page's code fails to load. The CSP allows no inline
// script, so this lives in its own file; a module in main.js's graph that fails to fetch or parse would otherwise
// leave the waiting placeholder up with no sign. Once main.js has drawn, the placeholder is gone and nothing changes.
{
  const MESSAGE =
    "codeteam deck: the page's code did not load (a file is missing or stale); restart `codeteam2 deck --web` and reload.";

  const pagePath = (filename) => {
    try {
      return new URL(filename, window.location.href).pathname;
    } catch {
      return "";
    }
  };

  window.addEventListener("error", (event) => {
    const waiting = document.querySelector("#deck .waiting");
    if (!waiting) return;
    const scriptFailed = event.target?.tagName === "SCRIPT";
    const pageCode = typeof event.filename === "string" && event.filename !== "" &&
      pagePath(event.filename).startsWith("/js/");
    if (scriptFailed || pageCode) waiting.textContent = MESSAGE;
  }, true);
}
