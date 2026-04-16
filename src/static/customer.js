// Customer phone logic
(function () {
  const CUSTOMER_ID = localStorage.getItem("vibecon_cid") || ("demo-" + Math.random().toString(36).slice(2, 8));
  localStorage.setItem("vibecon_cid", CUSTOMER_ID);

  const prechatScreen = document.getElementById("prechat-screen");
  const chatScreen = document.getElementById("chat-screen");
  const prechatBtn = document.getElementById("prechat-start");

  const messagesEl = document.getElementById("customer-messages");
  const inputEl = document.getElementById("customer-input");
  const sendBtn = document.getElementById("customer-send");
  const statusEl = document.getElementById("customer-status");

  let lastMessageId = null;
  let sending = false;
  let chatStarted = false;

  // The video source — determines the greeting context
  var entrySource = {
    video: "2021 Hyundai Creta SX Diesel Walkthrough",
    car: "2021 Hyundai Creta SX",
    price: "Rs 9.75L",
  };

  // --- Helpers ---

  function formatTime(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function waMarkdown(text) {
    return text
      .replace(/\*(.*?)\*/g, "<b>$1</b>")
      .replace(/_(.*?)_/g, "<i>$1</i>")
      .replace(/\n/g, "<br>");
  }

  function escapeHtml(text) {
    var div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function getApiHeaders(includeJson) {
    var headers = {};
    if (includeJson) headers["Content-Type"] = "application/json";
    var apiKey = localStorage.getItem("vyapari_api_key");
    if (apiKey) headers["X-API-Key"] = apiKey;
    return headers;
  }

  function createBubble(role, text, timestamp, images, isEscalation) {
    var bubble = document.createElement("div");
    bubble.className = "bubble " + role + (isEscalation ? " escalation" : "");

    if (images && images.length > 0) {
      images.forEach(function (url) {
        var img = document.createElement("img");
        img.src = url;
        img.loading = "lazy";
        img.onclick = function () { window.open(url, "_blank"); };
        img.onerror = function () { this.style.display = "none"; };
        bubble.appendChild(img);
      });
    }

    var textDiv = document.createElement("div");
    textDiv.innerHTML = waMarkdown(escapeHtml(text || ""));
    bubble.appendChild(textDiv);

    var meta = document.createElement("div");
    meta.className = "meta";
    meta.innerHTML = formatTime(timestamp);
    if (role === "customer") {
      meta.innerHTML += ' <span class="ticks">&#10003;&#10003;</span>';
    }
    bubble.appendChild(meta);

    return bubble;
  }

  function addSystemMessage(text, cls) {
    var el = document.createElement("div");
    el.className = "system-msg" + (cls ? " " + cls : "");
    el.textContent = text;
    messagesEl.appendChild(el);
    scrollDown();
  }

  function addTypingIndicator() {
    var el = document.createElement("div");
    el.className = "typing-indicator";
    el.id = "typing";
    el.innerHTML = "<span></span><span></span><span></span>";
    messagesEl.appendChild(el);
    scrollDown();
  }

  function removeTypingIndicator() {
    var el = document.getElementById("typing");
    if (el) el.remove();
  }

  function scrollDown() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  // --- Pre-chat → Chat transition ---

  prechatBtn.addEventListener("click", function () {
    prechatScreen.style.display = "none";
    chatScreen.style.display = "flex";
    chatScreen.classList.remove("hidden");
    startChat();
  });

  function startChat() {
    if (chatStarted) return;
    chatStarted = true;

    // Source-aware greeting — bot knows which video brought them
    addSystemMessage("Messages are end-to-end encrypted.");

    // Small delay to feel natural
    setTimeout(function () {
      messagesEl.appendChild(
        createBubble(
          "bot",
          "Hey! Saw you checking out our *" + entrySource.car + "* video \n\n" +
          "That one's a beauty — single owner, diesel, just *" + entrySource.price + "*. " +
          "Want the full details, or are you looking at other options too?",
          new Date().toISOString(),
          ["https://upload.wikimedia.org/wikipedia/commons/thumb/6/63/2020_Hyundai_Creta_SX_%28O%29_1.5_CRDi_%28front%29.png/800px-2020_Hyundai_Creta_SX_%28O%29_1.5_CRDi_%28front%29.png"],
          false
        )
      );
      scrollDown();
    }, 600);

    // Start polling
    setInterval(pollMessages, 2000);
    inputEl.focus();
  }

  // --- Send message ---

  async function sendMessage() {
    var text = inputEl.value.trim();
    if (!text || sending) return;

    sending = true;
    inputEl.value = "";
    sendBtn.disabled = true;

    messagesEl.appendChild(createBubble("customer", text, new Date().toISOString(), [], false));
    scrollDown();

    statusEl.textContent = "typing...";
    addTypingIndicator();

    try {
      var resp = await fetch("/api/chat", {
        method: "POST",
        headers: getApiHeaders(true),
        body: JSON.stringify({
          customer_id: CUSTOMER_ID,
          message: text,
          customer_name: "Customer (from Creta video)",
        }),
      });
      var data = await resp.json();

      removeTypingIndicator();
      statusEl.textContent = "online";

      if (data.reply) {
        messagesEl.appendChild(
          createBubble("bot", data.reply, new Date().toISOString(), data.images || [], data.is_escalation)
        );
        if (data.is_escalation) {
          addSystemMessage("Connecting you with our team...", "escalation-alert");
        }
      }
      scrollDown();
    } catch (err) {
      removeTypingIndicator();
      statusEl.textContent = "online";
      addSystemMessage("Connection error. Please try again.");
    }

    sending = false;
    sendBtn.disabled = false;
    inputEl.focus();
  }

  // --- Poll for owner messages ---

  async function pollMessages() {
    try {
      var url = "/api/messages/" + CUSTOMER_ID + (lastMessageId ? "?since_id=" + lastMessageId : "");
      var resp = await fetch(url, { headers: getApiHeaders(false) });
      var data = await resp.json();

      if (data.messages && data.messages.length > 0) {
        data.messages.forEach(function (msg) {
          if (msg.role === "owner") {
            messagesEl.appendChild(createBubble("bot", msg.text, msg.timestamp, msg.images || [], false));
            scrollDown();
          }
        });
        lastMessageId = data.messages[data.messages.length - 1].id;
      }
    } catch (err) { /* silent */ }
  }

  // --- Events ---

  sendBtn.addEventListener("click", sendMessage);
  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter") sendMessage();
  });
})();
