(function () {
  const shots = document.querySelectorAll("img.js-frigate[data-src]");
  if (!shots.length) return;

  function refresh() {
    shots.forEach((img) => {
      const base = img.getAttribute("data-src");
      if (!base) return;
      img.src = base + (base.indexOf("?") >= 0 ? "&" : "?") + "t=" + Date.now();
    });
  }

  setInterval(refresh, 10000);
})();
