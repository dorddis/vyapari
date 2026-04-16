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
    textDiv.innerHTML = waMarkdown(text);
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

  function renderOutboundMessage(msg) {
    if (!msg) return;

    if (msg.type === "typing") {
      addTypingIndicator();
      setTimeout(removeTypingIndicator, 1200);
      return;
    }

    if (msg.type === "text") {
      messagesEl.appendChild(
        createBubble("bot", (msg.content && msg.content.body) || "", msg.timestamp, [], false)
      );
      scrollDown();
      return;
    }

    if (msg.type === "image") {
      messagesEl.appendChild(
        createBubble(
          "bot",
          (msg.content && msg.content.caption) || "",
          msg.timestamp,
          [(msg.content && msg.content.url) || ""].filter(Boolean),
          false
        )
      );
      scrollDown();
      return;
    }

    if (msg.type === "buttons" || msg.type === "list") {
      messagesEl.appendChild(
        createBubble(
          "bot",
          (msg.content && msg.content.body) || "",
          msg.timestamp,
          msg.content && msg.content.image_url ? [msg.content.image_url] : [],
          false
        )
      );
      scrollDown();
    }
  }

  function renderQueuedMessages(messages) {
    if (!messages || messages.length === 0) return;
    messages.forEach(renderOutboundMessage);
    lastMessageId = messages[messages.length - 1].id;
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

    addSystemMessage("Messages are end-to-end encrypted.");

    statusEl.textContent = "typing...";
    addTypingIndicator();

    fetch("/api/chat/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customer_id: CUSTOMER_ID,
        customer_name: "Customer (from Creta video)",
        source: "creta_reel_apr16",
        source_car: entrySource.car,
        source_video: entrySource.video,
      }),
    })
      .then(function (resp) { return resp.json(); })
      .then(function (data) {
        removeTypingIndicator();
        statusEl.textContent = "online";
        if (data.reply) {
          messagesEl.appendChild(
            createBubble("bot", data.reply, new Date().toISOString(), data.images || [], false)
          );
          scrollDown();
        }
        renderQueuedMessages(data.messages || []);
      })
      .catch(function () {
        removeTypingIndicator();
        statusEl.textContent = "online";
        addSystemMessage("Connection error. Please try again.");
      });

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
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_id: CUSTOMER_ID,
          message: text,
          customer_name: "Customer (from Creta video)",
          source: "creta_reel_apr16",
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
      renderQueuedMessages(data.messages || []);
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
      var resp = await fetch(url);
      var data = await resp.json();

      if (data.messages && data.messages.length > 0) {
        renderQueuedMessages(data.messages);
      }
    } catch (err) { /* silent */ }
  }

  // --- Events ---

  sendBtn.addEventListener("click", sendMessage);
  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter") sendMessage();
  });
})();
