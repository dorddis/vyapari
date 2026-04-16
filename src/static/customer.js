// Customer phone logic
(function () {
  const CUSTOMER_ID = localStorage.getItem("vibecon_cid") || ("demo-" + Math.random().toString(36).slice(2, 8));
  localStorage.setItem("vibecon_cid", CUSTOMER_ID);

  const prechatScreen = document.getElementById("prechat-screen");
  const chatScreen = document.getElementById("chat-screen");
  const prechatBtn = document.getElementById("prechat-start");
  const customerHeader = document.getElementById("customer-header");
  const customerProfile = document.getElementById("customer-profile");
  const customerProfileBack = document.getElementById("customer-profile-back");

  const messagesEl = document.getElementById("customer-messages");
  const inputEl = document.getElementById("customer-input");
  const sendBtn = document.getElementById("customer-send");
  const statusEl = document.getElementById("customer-status");
  const profileViewCatalogueBtn = document.getElementById("profile-view-catalogue");
  const profileBudgetCatalogueBtn = document.getElementById("profile-budget-catalogue");

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

  function openChat() {
    prechatScreen.style.display = "none";
    chatScreen.style.display = "flex";
    chatScreen.classList.remove("hidden");
    if (customerProfile) {
      customerProfile.classList.add("hidden");
      customerProfile.setAttribute("aria-hidden", "true");
    }
    startChat();
  }

  function openProfile() {
    if (!chatStarted) {
      openChat();
    }
    customerProfile.classList.remove("hidden");
    customerProfile.setAttribute("aria-hidden", "false");
  }

  function closeProfile() {
    customerProfile.classList.add("hidden");
    customerProfile.setAttribute("aria-hidden", "true");
  }

  function addCatalogueCards(title, cars) {
    var block = document.createElement("div");
    block.className = "catalogue-block";

    var heading = document.createElement("div");
    heading.className = "catalogue-title";
    heading.textContent = title;
    block.appendChild(heading);

    var list = document.createElement("div");
    list.className = "catalogue-list";

    cars.forEach(function (car) {
      var card = document.createElement("div");
      card.className = "catalogue-card";

      if (car.image_url) {
        var img = document.createElement("img");
        img.src = car.image_url;
        img.loading = "lazy";
        img.onerror = function () { this.style.display = "none"; };
        card.appendChild(img);
      }

      var body = document.createElement("div");
      body.className = "catalogue-card-body";

      var titleEl = document.createElement("div");
      titleEl.className = "catalogue-card-title";
      titleEl.textContent = car.title || ((car.make || "") + " " + (car.model || "")).trim();
      body.appendChild(titleEl);

      var metaEl = document.createElement("div");
      metaEl.className = "catalogue-card-meta";
      metaEl.textContent = (car.fuel_type || "") + " · " + (car.transmission || "") + " · " +
        (Number(car.km_driven || 0).toLocaleString() + " km");
      body.appendChild(metaEl);

      var priceEl = document.createElement("div");
      priceEl.className = "catalogue-card-price";
      priceEl.textContent = "Rs " + car.price_lakhs + "L";
      body.appendChild(priceEl);

      var askBtn = document.createElement("button");
      askBtn.type = "button";
      askBtn.textContent = "Ask details";
      askBtn.addEventListener("click", function () {
        var carName = car.title || ((car.make || "") + " " + (car.model || "")).trim();
        var carId = car.id ? " (ID " + car.id + ")" : "";
        inputEl.value = "Share full details for " + carName + carId;
        inputEl.focus();
      });
      body.appendChild(askBtn);

      card.appendChild(body);
      list.appendChild(card);
    });

    block.appendChild(list);
    messagesEl.appendChild(block);
    scrollDown();
  }

  async function showCatalogue(options) {
    var title = options && options.title ? options.title : "Catalogue";
    var query = new URLSearchParams({ limit: "8" });

    if (options && options.maxPrice != null) query.set("max_price", String(options.maxPrice));
    if (options && options.minPrice != null) query.set("min_price", String(options.minPrice));
    if (options && options.fuelType) query.set("fuel_type", options.fuelType);
    if (options && options.make) query.set("make", options.make);
    if (options && options.transmission) query.set("transmission", options.transmission);

    statusEl.textContent = "fetching catalogue...";
    try {
      var resp = await fetch("/api/catalogue?" + query.toString(), { headers: getApiHeaders(false) });
      if (!resp.ok) throw new Error("catalogue fetch failed");
      var data = await resp.json();
      if (!data.cars || data.cars.length === 0) {
        addSystemMessage("No cars found for this filter.");
      } else {
        addCatalogueCards(title, data.cars);
      }
    } catch (err) {
      addSystemMessage("Could not load catalogue right now.");
    } finally {
      statusEl.textContent = "online";
    }
  }

  // --- Pre-chat → Chat transition ---

  prechatBtn.addEventListener("click", openChat);
  if (customerHeader) {
    customerHeader.addEventListener("click", openProfile);
    customerHeader.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openProfile();
      }
    });
  }
  if (customerProfileBack) {
    customerProfileBack.addEventListener("click", closeProfile);
  }

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
      if (!resp.ok) throw new Error("chat request failed");
      var data = await resp.json();

      removeTypingIndicator();
      statusEl.textContent = "online";

      if (data.reply) {
        messagesEl.appendChild(
          createBubble("bot", data.reply, new Date().toISOString(), data.images || [], data.is_escalation)
        );
      }

      if (data.mode === "owner") {
        addSystemMessage("Our team is replying directly now. Their message will appear here.");
      } else if (data.is_escalation) {
        addSystemMessage("Connecting you with our team...", "escalation-alert");
      } else if (!data.reply) {
        addSystemMessage("Please wait a moment while we process that.");
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
          if (msg.role === "owner" || msg.role === "sdr") {
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
  if (profileViewCatalogueBtn) {
    profileViewCatalogueBtn.addEventListener("click", function () {
      closeProfile();
      void showCatalogue({ title: "Live Catalogue" });
    });
  }
  if (profileBudgetCatalogueBtn) {
    profileBudgetCatalogueBtn.addEventListener("click", function () {
      closeProfile();
      void showCatalogue({ maxPrice: 8, title: "Cars Under Rs 8L" });
    });
  }
})();
