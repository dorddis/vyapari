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
  const chatHeader = document.getElementById("chat-header");
  const profilePanel = document.getElementById("profile-panel");
  const profileBackBtn = document.getElementById("profile-back");
  const profileInfoView = document.getElementById("profile-info-view");
  const profileCatalogueView = document.getElementById("profile-catalogue-view");
  const profileCatalogueBackBtn = document.getElementById("profile-catalogue-back");
  const profileCatalogueList = document.getElementById("profile-catalogue-list");
  const profileCatalogueTitle = document.getElementById("profile-catalogue-title");
  const profileViewCatalogueBtn = document.getElementById("profile-view-catalogue");
  const profileBudgetCatalogueBtn = document.getElementById("profile-budget-catalogue");

  let sending = false;

  function formatTime(iso) {
    const date = iso ? new Date(iso) : new Date();
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function openProfile() {
    profilePanel.classList.remove("hidden");
    profilePanel.setAttribute("aria-hidden", "false");
    showProfileInfo();
  }

  function closeProfile() {
    profilePanel.classList.add("hidden");
    profilePanel.setAttribute("aria-hidden", "true");
  }

  function showProfileInfo() {
    profileInfoView.classList.remove("hidden");
    profileInfoView.setAttribute("aria-hidden", "false");
    profileCatalogueView.classList.add("hidden");
    profileCatalogueView.setAttribute("aria-hidden", "true");
  }

  function showCatalogueView() {
    profileInfoView.classList.add("hidden");
    profileInfoView.setAttribute("aria-hidden", "true");
    profileCatalogueView.classList.remove("hidden");
    profileCatalogueView.setAttribute("aria-hidden", "false");
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

  function appendCatalogueCards(targetEl, title, cars) {
    targetEl.innerHTML = "";

    const block = document.createElement("div");
    block.className = "catalogue-block";

    const heading = document.createElement("div");
    heading.className = "catalogue-title";
    heading.textContent = title;
    block.appendChild(heading);

    const list = document.createElement("div");
    list.className = "catalogue-list";

    cars.forEach((car) => {
      const card = document.createElement("div");
      card.className = "catalogue-card";

      if (car.image_url) {
        const img = document.createElement("img");
        img.src = car.image_url;
        img.loading = "lazy";
        img.onerror = function () { this.style.display = "none"; };
        card.appendChild(img);
      }

      const body = document.createElement("div");
      body.className = "catalogue-card-body";

      const titleEl = document.createElement("div");
      titleEl.className = "catalogue-card-title";
      titleEl.textContent = car.title || "Car listing";
      body.appendChild(titleEl);

      const metaEl = document.createElement("div");
      metaEl.className = "catalogue-card-meta";
      metaEl.textContent = `${car.fuel_type || ""} · ${car.transmission || ""} · ${Number(car.km_driven || 0).toLocaleString()} km`;
      body.appendChild(metaEl);

      const priceEl = document.createElement("div");
      priceEl.className = "catalogue-card-price";
      priceEl.textContent = `Rs ${car.price_lakhs}L`;
      body.appendChild(priceEl);

      const askBtn = document.createElement("button");
      askBtn.type = "button";
      askBtn.textContent = "Ask details";
      askBtn.addEventListener("click", () => {
        const idSuffix = car.id ? ` (ID ${car.id})` : "";
        inputEl.value = `Share full details for ${car.title || "this car"}${idSuffix}`;
        inputEl.focus();
      });
      body.appendChild(askBtn);

      card.appendChild(body);
      list.appendChild(card);
    });

    block.appendChild(list);
    targetEl.appendChild(block);
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

  async function loadCatalogue(maxPrice) {
    profileCatalogueTitle.textContent = maxPrice != null ? `Cars under Rs ${maxPrice}L` : "Live Catalogue";
    profileCatalogueList.innerHTML = "";
    profileCatalogueList.appendChild(createLoadingState());
    showCatalogueView();
    try {
      const query = new URLSearchParams({ limit: "8" });
      if (maxPrice != null) {
        query.set("max_price", String(maxPrice));
      }
      const response = await fetch(`/api/catalogue?${query.toString()}`);
      if (!response.ok) {
        throw new Error("Failed to fetch catalogue");
      }
      const data = await response.json();
      if (!Array.isArray(data.cars) || data.cars.length === 0) {
        renderCatalogueMessage("No cars found for this filter.");
      } else {
        appendCatalogueCards(profileCatalogueList, profileCatalogueTitle.textContent, data.cars);
      }
    } catch (error) {
      renderCatalogueMessage("Could not load catalogue right now.");
    }
  }

  function createLoadingState() {
    const loading = document.createElement("div");
    loading.className = "profile-empty-state";
    loading.textContent = "Loading catalogue...";
    return loading;
  }

  function renderCatalogueMessage(text) {
    profileCatalogueList.innerHTML = "";
    const empty = document.createElement("div");
    empty.className = "profile-empty-state";
    empty.textContent = text;
    profileCatalogueList.appendChild(empty);
  }

  chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void sendMessage(inputEl.value);
  });

  chatHeader.addEventListener("click", openProfile);
  chatHeader.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openProfile();
    }
  });

  resetBtn.addEventListener("click", () => {
    void resetConversation();
  });

  if (quickActionsEl) {
    quickActionsEl.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLButtonElement)) {
        return;
      }
      void sendMessage(target.textContent || "");
    });
  }

  profileBackBtn.addEventListener("click", closeProfile);
  profileCatalogueBackBtn.addEventListener("click", showProfileInfo);
  profileViewCatalogueBtn.addEventListener("click", () => {
    void loadCatalogue();
  });
  profileBudgetCatalogueBtn.addEventListener("click", () => {
    void loadCatalogue(8);
  });

  void loadHistory();
})();
