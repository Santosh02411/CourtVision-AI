// Runs before first paint (kept external so the CSP can forbid inline scripts).
(function () {
  var theme = "dark";
  try {
    var saved = localStorage.getItem("cv.theme");
    if (saved === "light" || saved === "dark") theme = saved;
    else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) theme = "light";
  } catch (e) {}
  document.documentElement.setAttribute("data-theme", theme);
  var m = document.getElementById("meta-theme");
  if (m) m.setAttribute("content", theme === "light" ? "#f4f5f7" : "#07080a");
})();
