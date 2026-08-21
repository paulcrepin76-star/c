(() => {
  if (window.__restoCatalogHooked) return;
  window.__restoCatalogHooked = true;
  const push = (data) => {
    if (!data || typeof data !== "object") return;
    try {
      let node = document.getElementById("resto-catalog-bag");
      if (!node) {
        node = document.createElement("script");
        node.id = "resto-catalog-bag";
        node.type = "application/json";
        node.setAttribute("data-resto", "1");
        (document.documentElement || document.head).appendChild(node);
      }
      const current = JSON.parse(node.textContent || "[]");
      current.push(data);
      if (current.length > 60) current.splice(0, current.length - 60);
      node.textContent = JSON.stringify(current);
    } catch (_err) {
      /* ignore */
    }
  };
  const origFetch = window.fetch;
  if (typeof origFetch === "function") {
    window.fetch = async function (...args) {
      const response = await origFetch.apply(this, args);
      try {
        const type = response.headers.get("content-type") || "";
        if (type.includes("json")) {
          response.clone().json().then(push).catch(() => {});
        }
      } catch (_err) {
        /* ignore */
      }
      return response;
    };
  }
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (...args) {
    this.addEventListener("load", function () {
      try {
        const type = this.getResponseHeader("content-type") || "";
        if (type.includes("json") && this.responseText) {
          push(JSON.parse(this.responseText));
        }
      } catch (_err) {
        /* ignore */
      }
    });
    return origSend.apply(this, args);
  };
})();
