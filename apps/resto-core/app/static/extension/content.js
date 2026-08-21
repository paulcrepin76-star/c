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

function hookedPayloads() {
  const node = document.getElementById("resto-catalog-bag");
  if (!node) return [];
  try {
    const payload = JSON.parse(node.textContent || "[]");
    return Array.isArray(payload) ? payload : [payload];
  } catch (_err) {
    return [];
  }
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
        sku: String(block.sku || block.gtin13 || block.gtin || ""),
        brand: brandName(block.brand),
        url: String(offers.url || block.url || location.href),
        discount: Boolean(offers.price && offers.highPrice && Number(offers.price) < Number(offers.highPrice)),
        available: offers.availability ? !/OutOfStock/i.test(String(offers.availability)) : true,
      });
    }
  }
  Object.values(block).forEach((value) => {
    if (value && typeof value === "object") walkLd(value, items);
  });
}

function brandName(value) {
  if (!value) return "";
  if (typeof value === "string") return value;
  return String(value.name || "");
}

function numberish(value) {
  if (value == null || value === "") return null;
  if (typeof value === "object") {
    return numberish(value.price || value.amount || value.salePrice || value.finalPrice);
  }
  const amount = Number(String(value).replace(/[^0-9.]/g, ""));
  return Number.isFinite(amount) && amount > 0 ? amount : null;
}

function flattenProducts(payload, items, depth) {
  const out = items || [];
  const level = depth || 0;
  if (level > 8 || out.length >= 200) return out;
  if (Array.isArray(payload)) {
    payload.forEach((entry) => flattenProducts(entry, out, level + 1));
    return out;
  }
  if (!payload || typeof payload !== "object") return out;
  const name = payload.name || payload.title || payload.productName || payload.description;
  const price = numberish(
    payload.salePrice || payload.finalPrice || payload.price || payload.currentPrice || payload.listPrice
  );
  if (name && price && String(name).length >= 4) {
    const list = numberish(payload.listPrice || payload.regularPrice || payload.price);
    out.push({
      name: String(name),
      pack: String(payload.size || payload.pack || payload.packSize || payload.description || ""),
      price,
      upc: String(payload.upc || payload.gtin || payload.gtin13 || ""),
      sku: String(payload.sku || payload.itemNumber || payload.itemId || payload.upc || ""),
      brand: brandName(payload.brand || payload.brandName),
      url: String(payload.url || payload.link || payload.canonicalUrl || location.href),
      discount: Boolean(list && price < list),
      available: payload.available !== false && payload.inStock !== false,
      regular_price: list || price,
      promo_price: payload.salePrice || payload.finalPrice ? price : null,
    });
  }
  Object.values(payload).forEach((value) => {
    if (value && typeof value === "object") flattenProducts(value, out, level + 1);
  });
  return out;
}

function embeddedState() {
  const items = [];
  const next = document.getElementById("__NEXT_DATA__");
  if (next) {
    try {
      flattenProducts(JSON.parse(next.textContent || "null"), items);
    } catch (_err) {
      /* ignore */
    }
  }
  document.querySelectorAll("script").forEach((node) => {
    const text = (node.textContent || "").trim();
    if (text.length < 40 || (text[0] !== "{" && text[0] !== "[")) return;
    try {
      flattenProducts(JSON.parse(text), items);
    } catch (_err) {
      /* ignore */
    }
  });
  if (window.__restoCatalogBag) {
    window.__restoCatalogBag.forEach((payload) => flattenProducts(payload, items));
  }
  hookedPayloads().forEach((payload) => flattenProducts(payload, items));
  return items;
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
      sku: "",
      brand: "",
      url: location.href,
      discount: /sale|promo|save/i.test(blob),
      available: true,
    });
  });
  return items.slice(0, 40);
}

function dedupe(items) {
  const seen = new Set();
  const unique = [];
  items.forEach((item) => {
    const key = `${(item.sku || item.upc || item.name || "").toLowerCase()}|${item.price}`;
    if (seen.has(key)) return;
    seen.add(key);
    unique.push(item);
  });
  return unique;
}

function matchesWatch(item, watch) {
  if (!watch || !watch.length) return true;
  const blob = `${item.name} ${item.pack} ${item.sku} ${item.upc}`.toLowerCase();
  return watch.some((row) => (row.needles || []).some((needle) => needle && blob.includes(String(needle).toLowerCase())));
}

function pickItems(watch) {
  const json = dedupe(embeddedState());
  const ld = jsonLdItems();
  const visible = visibleFallback();
  const preferred = json.length ? json : ld.length ? ld : visible;
  const relevant = preferred.filter((item) => matchesWatch(item, watch));
  const chosen = relevant.length ? relevant : preferred;
  return chosen.slice(0, 40);
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const collect = message === "collect" || (message && message.type === "collect");
  if (!collect) return;
  const items = pickItems((message && message.watch) || []);
  sendResponse({
    supplier: hostSupplier(location.hostname),
    store: "",
    page_url: location.href,
    items,
  });
  return true;
});
