const cellarUrl = document.getElementById("cellarUrl");
const apiKey = document.getElementById("apiKey");
const status = document.getElementById("status");

chrome.storage.sync.get(["cellarUrl", "apiKey"], (config) => {
  cellarUrl.value = config.cellarUrl || "http://100.116.48.120:8088";
  apiKey.value = config.apiKey || "";
});

document.getElementById("save").addEventListener("click", () => {
  chrome.storage.sync.set(
    { cellarUrl: cellarUrl.value.trim(), apiKey: apiKey.value.trim() },
    () => {
      status.textContent = "Saved.";
    }
  );
});
