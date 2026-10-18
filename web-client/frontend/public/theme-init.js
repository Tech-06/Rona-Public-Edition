// Runs synchronously from <head> (before first paint) so the saved theme is
// applied without a flash. External rather than inline so the CSP can stay
// `script-src 'self'` (see webui/server.py).
(function () {
  var root = document.documentElement;
  var dark = true;
  try {
    var stored = localStorage.getItem("rona:theme");
    var mode = stored === "light" || stored === "dark" ? stored : "system";
    dark =
      mode === "dark" ||
      (mode === "system" &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);
  } catch (e) {
    // private mode / storage unavailable: fall back to dark
  }
  root.classList.toggle("dark", dark);
  root.style.colorScheme = dark ? "dark" : "light";
  root.style.backgroundColor = dark ? "#0f1115" : "#ffffff";
  var themeColorMeta = document.querySelector('meta[name="theme-color"]');
  if (themeColorMeta) themeColorMeta.setAttribute("content", dark ? "#171717" : "#f7f7f8");
})();
