const cellarUrl = document.getElementById("cellarUrl");
const apiKey = document.getElementById("apiKey");
const status = document.getElementById("status");

function store() {
  return chrome.storage.local;
}

function normalizeUrl(value) {
  return String(value || "").trim().replace(/\/$/, "");
}

function problemWith(url, key) {
  const base = url.toLowerCase();
  if (!url) return "Cellar URL is empty.";
  if (base.includes(":5678") || base.includes("n8n")) {
    return "That is n8n. Use http://100.116.48.120:8088";
  }
  if (!/^https?:\/\//i.test(url)) return "Cellar URL must start with http://";
  if (!key) return "Paste the cellar API key from the Prices page, not n8n.";
  if (/^n8n_/i.test(key) || key.includes("n8n")) {
    return "That looks like an n8n key. Copy the cellar key from http://100.116.48.120:8088/collector";
  }
  return "";
}

store().get(["cellarUrl", "apiKey"], (config) => {
  cellarUrl.value = config.cellarUrl || "http://100.116.48.120:8088";
  apiKey.value = config.apiKey || "";
});

document.getElementById("save").addEventListener("click", () => {
  const url = normalizeUrl(cellarUrl.value);
  const key = apiKey.value.trim();
  const problem = problemWith(url, key);
  if (problem) {
    status.className = "err";
    status.textContent = problem;
    return;
  }
  cellarUrl.value = url;
  store().set({ cellarUrl: url, apiKey: key }, () => {
    if (chrome.runtime.lastError) {
      status.className = "err";
      status.textContent = chrome.runtime.lastError.message;
      return;
    }
    status.className = "ok";
    status.textContent = "Saved. Click Test connection.";
  });
});

document.getElementById("test").addEventListener("click", async () => {
  const url = normalizeUrl(cellarUrl.value);
  const key = apiKey.value.trim();
  const problem = problemWith(url, key);
  if (problem) {
    status.className = "err";
    status.textContent = problem;
    return;
  }
  status.className = "muted";
  status.textContent = "Testing…";
  try {
    const response = await fetch(`${url}/api/prices/ping`, {
      headers: { "X-API-Key": key },
    });
    if (response.status === 401) {
      status.className = "err";
      status.textContent = "Key rejected. Copy it from Prices on port 8088, not from n8n.";
      return;
    }
    if (!response.ok) {
      status.className = "err";
      status.textContent = `Cellar answered ${response.status}. URL should be http://100.116.48.120:8088`;
      return;
    }
    store().set({ cellarUrl: url, apiKey: key });
    try {
      const watch = await fetch(`${url}/api/prices/watch`, { headers: { "X-API-Key": key } });
      if (watch.ok) {
        const body = await watch.json();
        store().set({ watchProducts: body.products || [] });
        status.className = "ok";
        status.textContent = `Connected to the cellar. Watching ${body.count || 0} item(s) you buy.`;
        return;
      }
    } catch (_err) {
      /* ping already succeeded */
    }
    status.className = "ok";
    status.textContent = "Connected to the cellar.";
  } catch (err) {
    status.className = "err";
    status.textContent = "Could not reach the cellar. Use port 8088, and stay on Tailscale.";
  }
});
