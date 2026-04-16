(function () {
  const storageKey = "vyapari_demo_customer_id";
  const customerId = localStorage.getItem(storageKey) || `demo-${Math.random().toString(36).slice(2, 9)}`;
  localStorage.setItem(storageKey, customerId);

  const messagesEl = document.getElementById("messages");
  const statusEl = document.getElementById("chat-status");
  const chatForm = document.getElementById("chat-form");
  const inputEl = document.getElementById("message-input");
  const sendBtn = document.getElementById("send-btn");
  const resetBtn = document.getElementById("reset-chat");
  const quickActionsEl = document.getElementById("quick-actions");

  let sending = false;

  function formatTime(iso) {
    const date = iso ? new Date(iso) : new Date();
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function appendBubble(role, text, timestamp) {
    const bubble = document.createElement("div");
    bubble.className = `bubble ${role}`;

    const textEl = document.createElement("div");
    textEl.textContent = text;
    bubble.appendChild(textEl);

    const metaEl = document.createElement("div");
    metaEl.className = "meta";
    metaEl.textContent = formatTime(timestamp);
    bubble.appendChild(metaEl);

    messagesEl.appendChild(bubble);
    scrollToBottom();
  }

  function appendSystemMessage(text) {
    const system = document.createElement("div");
    system.className = "bubble system";
    system.textContent = text;
    messagesEl.appendChild(system);
    scrollToBottom();
  }

  function addTyping() {
    const typing = document.createElement("div");
    typing.className = "typing";
    typing.id = "typing-indicator";
    typing.innerHTML = "<span></span><span></span><span></span>";
    messagesEl.appendChild(typing);
    scrollToBottom();
  }

  function removeTyping() {
    const typing = document.getElementById("typing-indicator");
    if (typing) {
      typing.remove();
    }
  }

  function setSendingState(isSending) {
    sending = isSending;
    sendBtn.disabled = isSending;
    statusEl.textContent = isSending ? "typing..." : "online";
  }

  async function loadHistory() {
    try {
      const response = await fetch(`/api/messages/${customerId}`);
      if (!response.ok) {
        throw new Error("Failed to load history");
      }
      const data = await response.json();
      messagesEl.innerHTML = "";

      if (!Array.isArray(data.messages) || data.messages.length === 0) {
        appendSystemMessage("Connected to the live demo backend.");
        appendBubble("bot", "Namaste! Ask about cars, pricing, or a test drive.");
        return;
      }

      data.messages.forEach((message) => {
        if (message.role === "customer") {
          appendBubble("customer", message.text, message.timestamp);
        } else {
          appendBubble("bot", message.text, message.timestamp);
        }
      });
    } catch (error) {
      appendSystemMessage("Could not load previous chat. You can still continue.");
    }
  }

  async function sendMessage(text) {
    const cleanText = text.trim();
    if (!cleanText || sending) {
      return;
    }

    appendBubble("customer", cleanText, new Date().toISOString());
    inputEl.value = "";
    setSendingState(true);
    addTyping();

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_id: customerId,
          customer_name: "Demo Customer",
          message: cleanText,
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to send");
      }

      const data = await response.json();
      removeTyping();
      appendBubble("bot", data.reply || "No reply from backend.", new Date().toISOString());
    } catch (error) {
      removeTyping();
      appendSystemMessage("Send failed. Check backend and try again.");
    } finally {
      setSendingState(false);
      inputEl.focus();
    }
  }

  async function resetConversation() {
    try {
      await fetch("/api/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ customer_id: customerId }),
      });
      await loadHistory();
    } catch (error) {
      appendSystemMessage("Reset failed. Try again.");
    }
  }

  chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void sendMessage(inputEl.value);
  });

  resetBtn.addEventListener("click", () => {
    void resetConversation();
  });

  quickActionsEl.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) {
      return;
    }
    void sendMessage(target.textContent || "");
  });

  void loadHistory();
})();
