chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== "send") return;
  chrome.storage.sync.get(["cellarUrl", "apiKey"], async (config) => {
    const base = (config.cellarUrl || "http://100.116.48.120:8088").replace(/\/$/, "");
    const key = config.apiKey || "";
    try {
      const response = await fetch(`${base}/api/prices/collect`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": key,
        },
        body: JSON.stringify(message.payload),
      });
      const body = await response.json().catch(() => ({}));
      sendResponse({ ok: response.ok, status: response.status, body });
    } catch (err) {
      sendResponse({ ok: false, error: String(err) });
    }
  });
  return true;
});
