// Owner phone logic
(function () {
  var convoListEl = document.getElementById("convo-list");
  var panelConvos = document.getElementById("panel-convos");
  var panelChat = document.getElementById("panel-chat");
  var panelOracle = document.getElementById("panel-oracle");

  var ownerMessagesEl = document.getElementById("owner-messages");
  var ownerInputEl = document.getElementById("owner-input");
  var ownerSendBtn = document.getElementById("owner-send");
  var ownerBackBtn = document.getElementById("owner-back");
  var ownerChatName = document.getElementById("owner-chat-name");
  var modePill = document.getElementById("mode-pill");

  var oracleMessagesEl = document.getElementById("oracle-messages");
  var oracleInputEl = document.getElementById("oracle-input");
  var oracleSendBtn = document.getElementById("oracle-send");

  var tabs = document.querySelectorAll(".tab-bar button");

  var activeCustomerId = null;
  var activeTab = "convos";
  var ownerLastMsgId = null;
  var ownerSending = false;

  // --- Helpers ---

  function formatTime(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function formatTimeShort(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    var now = new Date();
    if (d.toDateString() === now.toDateString()) {
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
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

  function scrollDown(el) {
    el.scrollTop = el.scrollHeight;
  }

  // --- Owner-view bubble (with role labels) ---

  function createOwnerViewBubble(role, text, timestamp, images, isEscalation) {
    var wrapper = document.createElement("div");
    wrapper.style.display = "flex";
    wrapper.style.flexDirection = "column";
    wrapper.style.alignItems = role === "owner" ? "flex-end" : "flex-start";
    wrapper.style.marginBottom = "2px";

    // Role label (except for owner — that's obvious)
    if (role === "customer" || role === "bot") {
      var label = document.createElement("div");
      label.className = "bubble-label " + role;
      label.textContent = role === "customer" ? "Customer" : "AI Bot";
      wrapper.appendChild(label);
    }

    var bubble = document.createElement("div");
    bubble.className = "bubble owner-view-" + role + (isEscalation ? " escalation" : "");

    if (images && images.length > 0) {
      images.forEach(function (url) {
        var img = document.createElement("img");
        img.src = url;
        img.loading = "lazy";
        img.onerror = function () { this.style.display = "none"; };
        bubble.appendChild(img);
      });
    }

    var textDiv = document.createElement("div");
    textDiv.innerHTML = waMarkdown(escapeHtml(text || ""));
    bubble.appendChild(textDiv);

    var meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = formatTime(timestamp);
    bubble.appendChild(meta);

    wrapper.appendChild(bubble);
    return wrapper;
  }

  // Oracle bubble (simpler)
  function createOracleBubble(role, text, timestamp) {
    var bubble = document.createElement("div");
    bubble.className = "bubble " + (role === "customer" ? "customer" : "bot");

    var textDiv = document.createElement("div");
    textDiv.innerHTML = waMarkdown(escapeHtml(text || ""));
    bubble.appendChild(textDiv);

    var meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = formatTime(timestamp);
    bubble.appendChild(meta);

    return bubble;
  }

  // --- Tab switching ---

  function switchTab(tab) {
    activeTab = tab;
    tabs.forEach(function (t) { t.classList.toggle("active", t.dataset.tab === tab); });
    panelConvos.classList.toggle("active", tab === "convos");
    panelChat.classList.remove("active");
    panelOracle.classList.toggle("active", tab === "oracle");
    if (tab === "convos") activeCustomerId = null;
  }

  tabs.forEach(function (t) {
    t.addEventListener("click", function () { switchTab(this.dataset.tab); });
  });

  // --- Conversations list ---

  async function loadConversations() {
    try {
      var resp = await fetch("/api/conversations", { headers: getApiHeaders(false) });
      var data = await resp.json();
      renderConvoList(data.conversations);
    } catch (err) { /* silent */ }
  }

  function renderConvoList(convos) {
    if (convos.length === 0) {
      convoListEl.innerHTML = '<div class="empty-state">No conversations yet.<br>Wait for a customer to start chatting.</div>';
      return;
    }

    convoListEl.innerHTML = "";
    convos.forEach(function (c) {
      var card = document.createElement("div");
      card.className = "convo-card" + (c.has_escalation ? " escalated" : "");

      var initial = c.customer_name.charAt(0).toUpperCase();
      var badgeClass = c.mode === "escalated" ? "escalated" : c.mode === "owner" ? "owner" : "bot";
      var badgeText = c.mode === "escalated" ? "ESCALATED" : c.mode === "owner" ? "YOU" : "BOT";

      card.innerHTML =
        '<div class="avatar">' + initial + '</div>' +
        '<div class="details">' +
          '<div class="name">' + escapeHtml(c.customer_name) +
            ' <span class="badge ' + badgeClass + '">' + badgeText + '</span>' +
          '</div>' +
          '<div class="preview">' + escapeHtml(c.last_message) + '</div>' +
        '</div>' +
        '<div class="time">' + formatTimeShort(c.last_activity) + '</div>';

      card.addEventListener("click", function () { openConversation(c.customer_id, c.customer_name, c.mode); });
      convoListEl.appendChild(card);
    });
  }

  // --- Conversation detail ---

  async function openConversation(customerId, name, mode) {
    activeCustomerId = customerId;
    ownerChatName.textContent = name;
    ownerLastMsgId = null;

    panelConvos.classList.remove("active");
    panelChat.classList.add("active");

    updateModePill(mode);

    ownerMessagesEl.innerHTML = "";
    try {
      var resp = await fetch("/api/messages/" + customerId, { headers: getApiHeaders(false) });
      var data = await resp.json();
      data.messages.forEach(function (msg) {
        if (msg.is_escalation) {
          var alert = document.createElement("div");
          alert.className = "system-msg escalation-alert";
          alert.textContent = "ESCALATION: " + (msg.escalation_reason || "Customer needs attention");
          ownerMessagesEl.appendChild(alert);
        }
        ownerMessagesEl.appendChild(
          createOwnerViewBubble(msg.role, msg.text, msg.timestamp, msg.images || [], msg.is_escalation)
        );
      });
      if (data.messages.length > 0) {
        ownerLastMsgId = data.messages[data.messages.length - 1].id;
      }

      // Show hint when owner opens an escalated/active convo
      if (mode === "escalated" || mode === "owner") {
        addOwnerHint("Type to reply directly to customer. Type /done to hand back to AI.");
      }

      scrollDown(ownerMessagesEl);
    } catch (err) {
      ownerMessagesEl.innerHTML = '<div class="empty-state">Error loading messages</div>';
    }
  }

  function addOwnerHint(text) {
    var el = document.createElement("div");
    el.className = "system-msg";
    el.textContent = text;
    ownerMessagesEl.appendChild(el);
  }

  function updateModePill(mode) {
    modePill.className = "mode-pill " + mode;
    modePill.textContent = mode === "escalated" ? "Escalated" : mode === "owner" ? "You" : "Bot";
  }

  // --- Owner send (hijack) + /done command ---

  async function ownerSend() {
    if (ownerSending) return;

    var text = ownerInputEl.value.trim();
    if (!text || !activeCustomerId) return;
    ownerInputEl.value = "";

    // /done command = release to bot
    if (text.toLowerCase() === "/done") {
      ownerSending = true;
      ownerSendBtn.disabled = true;
      try {
        await fetch("/api/owner/release", {
          method: "POST",
          headers: getApiHeaders(true),
          body: JSON.stringify({ customer_id: activeCustomerId }),
        });
        updateModePill("bot");
        var sys = document.createElement("div");
        sys.className = "system-msg";
        sys.textContent = "Handed back to AI bot.";
        ownerMessagesEl.appendChild(sys);
        scrollDown(ownerMessagesEl);
      } catch (err) { /* silent */ }
      finally {
        ownerSending = false;
        ownerSendBtn.disabled = false;
      }
      return;
    }

    // Normal message = hijack
    ownerMessagesEl.appendChild(
      createOwnerViewBubble("owner", text, new Date().toISOString(), [], false)
    );
    scrollDown(ownerMessagesEl);

    ownerSending = true;
    ownerSendBtn.disabled = true;
    try {
      var resp = await fetch("/api/owner/send", {
        method: "POST",
        headers: getApiHeaders(true),
        body: JSON.stringify({ customer_id: activeCustomerId, message: text }),
      });
      var data = await resp.json();
      updateModePill(data.mode);

      // Show hint on first hijack
      if (data.mode === "owner") {
        addOwnerHint("You're now talking directly. Customer sees your messages. Type /done when finished.");
      }
    } catch (err) { /* silent */ }
    finally {
      ownerSending = false;
      ownerSendBtn.disabled = false;
    }
  }

  ownerSendBtn.addEventListener("click", ownerSend);
  ownerInputEl.addEventListener("keydown", function (e) { if (e.key === "Enter") ownerSend(); });

  // --- Back button ---

  ownerBackBtn.addEventListener("click", function () {
    activeCustomerId = null;
    panelChat.classList.remove("active");
    panelConvos.classList.add("active");
  });

  // --- Oracle ---

  async function oracleQuery() {
    var text = oracleInputEl.value.trim();
    if (!text) return;
    oracleInputEl.value = "";

    oracleMessagesEl.appendChild(createOracleBubble("customer", text, new Date().toISOString()));
    scrollDown(oracleMessagesEl);

    var typing = document.createElement("div");
    typing.className = "typing-indicator";
    typing.innerHTML = "<span></span><span></span><span></span>";
    oracleMessagesEl.appendChild(typing);
    scrollDown(oracleMessagesEl);

    try {
      var resp = await fetch("/api/owner/query", {
        method: "POST",
        headers: getApiHeaders(true),
        body: JSON.stringify({ query: text }),
      });
      var data = await resp.json();
      typing.remove();

      oracleMessagesEl.appendChild(createOracleBubble("bot", data.text, new Date().toISOString()));

      if (data.action && data.action.success) {
        var sys = document.createElement("div");
        sys.className = "system-msg";
        sys.textContent = "Done: " + data.action.car_name + " marked as sold";
        oracleMessagesEl.appendChild(sys);
      }
      scrollDown(oracleMessagesEl);
    } catch (err) {
      typing.remove();
      oracleMessagesEl.appendChild(createOracleBubble("bot", "Sorry, something went wrong.", new Date().toISOString()));
      scrollDown(oracleMessagesEl);
    }
  }

  oracleSendBtn.addEventListener("click", oracleQuery);
  oracleInputEl.addEventListener("keydown", function (e) { if (e.key === "Enter") oracleQuery(); });

  // --- Poll for new messages in open conversation ---

  async function pollActiveConvo() {
    if (!activeCustomerId) return;
    // Only poll when chat panel is visible
    if (!panelChat.classList.contains("active")) return;

    try {
      var url = "/api/messages/" + activeCustomerId + (ownerLastMsgId ? "?since_id=" + ownerLastMsgId : "");
      var resp = await fetch(url, { headers: getApiHeaders(false) });
      var data = await resp.json();

      if (data.messages && data.messages.length > 0) {
        data.messages.forEach(function (msg) {
          if (msg.is_escalation) {
            var alert = document.createElement("div");
            alert.className = "system-msg escalation-alert";
            alert.textContent = "ESCALATION: " + (msg.escalation_reason || "Customer needs attention");
            ownerMessagesEl.appendChild(alert);
          }
          ownerMessagesEl.appendChild(
            createOwnerViewBubble(msg.role, msg.text, msg.timestamp, msg.images || [], false)
          );
        });
        ownerLastMsgId = data.messages[data.messages.length - 1].id;
        scrollDown(ownerMessagesEl);
      }

      updateModePill(data.mode);
    } catch (err) { /* silent */ }
  }

  // --- Polling ---
  setInterval(loadConversations, 3000);
  setInterval(pollActiveConvo, 2000);
  loadConversations();
})();
