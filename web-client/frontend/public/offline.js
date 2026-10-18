// External (not inline) so the CSP can stay `script-src 'self'`. The theme is
// applied earlier, from <head>, by /theme-init.js.
(function () {
  var STRINGS = {
    tr: {
      title: "Rona sunucusuna ulaşılamıyor",
      detail: "Bağlantını kontrol et, sonra tekrar dene.",
      retry: "Tekrar dene",
    },
    en: {
      title: "Can't reach the Rona server",
      detail: "Check your connection, then try again.",
      retry: "Try again",
    },
  };
  var lang = "tr";
  try {
    var stored = localStorage.getItem("rona:lang");
    if (stored === "tr" || stored === "en") lang = stored;
  } catch (e) {
    // private mode / storage unavailable: fall back to tr
  }
  document.documentElement.lang = lang;
  var strings = STRINGS[lang];
  document.querySelectorAll("[data-t]").forEach(function (node) {
    var key = node.getAttribute("data-t");
    if (strings[key]) node.textContent = strings[key];
  });
  // The server coming back is the one thing worth reacting to on its
  // own -- a background reload, not just re-showing the button.
  var retry = document.getElementById("retry");
  if (retry) {
    retry.addEventListener("click", function () {
      location.reload();
    });
  }
  window.addEventListener("online", function () {
    location.reload();
  });
})();
