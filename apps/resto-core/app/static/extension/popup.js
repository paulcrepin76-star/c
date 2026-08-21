const status = document.getElementById("status");
const button = document.getElementById("send");

button.addEventListener("click", async () => {
  status.textContent = "Reading this page…";
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) {
    status.textContent = "No active tab.";
    return;
  }
  let page;
  try {
    page = await chrome.tabs.sendMessage(tab.id, "collect");
  } catch (err) {
    status.textContent = "This site is not in the collector list, or reload the tab.";
    return;
  }
  if (!page || !page.items || !page.items.length) {
    status.textContent = "No prices visible. Open a product or search results first.";
    return;
  }
  status.textContent = `Sending ${page.items.length} pack(s) from ${page.supplier}…`;
  chrome.runtime.sendMessage(
    {
      type: "send",
      payload: {
        supplier: page.supplier,
        store: page.store || "",
        source: "extension",
        page_url: page.page_url,
        items: page.items,
      },
    },
    (result) => {
      if (!result || !result.ok) {
        status.textContent = result && result.body && result.body.detail
          ? String(result.body.detail)
          : "Could not reach the cellar. Check the API key and cellar URL in Options.";
        return;
      }
      const recorded = (result.body && result.body.recorded) || 0;
      status.textContent = `Recorded ${recorded} matching pack(s). Open Purchasing on the cellar.`;
    }
  );
});
