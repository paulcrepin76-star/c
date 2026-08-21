function hostSupplier(host) {
  const map = [
    ["samsclub.com", "Sam's Club"],
    ["costco.com", "Costco"],
    ["walmart.com", "Walmart"],
    ["publix.com", "Publix"],
    ["target.com", "Target"],
    ["aldi.us", "Aldi"],
    ["chefswarehouse.com", "Chef's Warehouse"],
    ["gfs.com", "Gordon Food Service"],
    ["restaurantdepot.com", "Restaurant Depot"],
    ["sysco.com", "Sysco"],
    ["webstaurantstore.com", "WebstaurantStore"],
  ];
  const hit = map.find(([needle]) => host.includes(needle));
  return hit ? hit[1] : host.replace(/^www\./, "");
}

function jsonLdItems() {
  const items = [];
  document.querySelectorAll('script[type="application/ld+json"]').forEach((node) => {
    try {
      const payload = JSON.parse(node.textContent || "null");
      const blocks = Array.isArray(payload) ? payload : [payload];
      blocks.forEach((block) => walkLd(block, items));
    } catch (_err) {
      /* ignore bad JSON-LD */
    }
  });
  return items;
}

function walkLd(block, items) {
  if (!block || typeof block !== "object") return;
  const types = [].concat(block["@type"] || []);
  if (types.some((value) => String(value).toLowerCase() === "product") && block.name) {
    const offers = Array.isArray(block.offers) ? block.offers[0] : block.offers || {};
    const price = offers.price || offers.lowPrice;
    if (price) {
      items.push({
        name: String(block.name),
        pack: String(block.size || block.description || ""),
        price: Number(price),
        upc: String(block.sku || block.gtin13 || block.gtin || ""),
        url: String(offers.url || block.url || location.href),
        discount: Boolean(offers.price && offers.highPrice && Number(offers.price) < Number(offers.highPrice)),
      });
    }
  }
  Object.values(block).forEach((value) => {
    if (value && typeof value === "object") walkLd(value, items);
  });
}

function visibleFallback() {
  const items = [];
  const seen = new Set();
  document.querySelectorAll("h1, h2, h3, [data-testid], [itemprop=name]").forEach((node) => {
    const name = (node.textContent || "").trim().replace(/\s+/g, " ");
    if (name.length < 4 || name.length > 160) return;
    const blob = ((node.closest("article, li, section, div") || node.parentElement || node).textContent || "");
    const match = blob.match(/\$(\d+(?:\.\d{1,2})?)/);
    if (!match) return;
    const key = name.toLowerCase() + match[1];
    if (seen.has(key)) return;
    seen.add(key);
    items.push({
      name,
      pack: "",
      price: Number(match[1]),
      upc: "",
      url: location.href,
      discount: /sale|promo|save/i.test(blob),
    });
  });
  return items.slice(0, 40);
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message !== "collect") return;
  const ld = jsonLdItems();
  const items = ld.length ? ld : visibleFallback();
  sendResponse({
    supplier: hostSupplier(location.hostname),
    store: "",
    page_url: location.href,
    items,
  });
  return true;
});
