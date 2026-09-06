(function () {
  const log = document.getElementById("chat-log");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const send = document.getElementById("chat-send");
  if (!log || !form || !input) return;

  function bubble(text, kind) {
    const node = document.createElement("p");
    node.className = "chat-msg " + kind;
    node.textContent = text;
    log.appendChild(node);
    log.scrollTop = log.scrollHeight;
    return node;
  }

  async function ask(message) {
    bubble(message, "me");
    const waiting = bubble("…", "bot waiting");
    input.value = "";
    input.disabled = true;
    send.disabled = true;
    try {
      const response = await fetch("/assistant/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message }),
      });
      const data = await response.json();
      waiting.textContent = data.reply || "No answer came back.";
      waiting.className = "chat-msg bot" + (data.ok ? "" : " err");
    } catch (error) {
      waiting.textContent = "The page could not reach the assistant.";
      waiting.className = "chat-msg bot err";
    } finally {
      input.disabled = false;
      send.disabled = false;
      input.focus();
    }
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    const message = input.value.trim();
    if (message) ask(message);
  });

  document.querySelectorAll("[data-ask]").forEach(function (chip) {
    chip.addEventListener("click", function () {
      ask(chip.getAttribute("data-ask"));
    });
  });
})();
