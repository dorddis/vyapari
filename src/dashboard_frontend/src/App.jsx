import { startTransition, useDeferredValue, useState } from "react";
import {
  conversationSeeds,
  insightCards,
  inventorySeeds,
  leadStageData,
  onboardingSteps,
  ownerAgentSeed,
  priceBandDemand,
  sourceBreakdown,
  weeklyLeadTrend,
} from "./data";

const navItems = [
  { id: "inbox", label: "Leads", note: "Respond only when needed" },
  { id: "inventory", label: "Stock", note: "Track live availability" },
  { id: "insights", label: "Insights", note: "See where demand is moving" },
];

const filterChips = ["all", "hot", "warm", "new", "escalated"];

function App() {
  const [activeView, setActiveView] = useState("inbox");
  const [conversations, setConversations] = useState(conversationSeeds);
  const [selectedId, setSelectedId] = useState(conversationSeeds[0].id);
  const [leadFilter, setLeadFilter] = useState("all");
  const [leadQuery, setLeadQuery] = useState("");
  const [replyDraft, setReplyDraft] = useState("");
  const [agentDraft, setAgentDraft] = useState("");
  const [agentMessages, setAgentMessages] = useState(ownerAgentSeed);

  const deferredLeadQuery = useDeferredValue(leadQuery);
  const selectedConversation =
    conversations.find((conversation) => conversation.id === selectedId) ??
    conversations[0];

  const visibleConversations = conversations.filter((conversation) => {
    const matchesFilter =
      leadFilter === "all"
        ? true
        : leadFilter === "escalated"
          ? conversation.needsAttention
          : conversation.status === leadFilter;
    const searchableText = [
      conversation.name,
      conversation.source,
      conversation.status,
      conversation.vehicleInterest.join(" "),
      conversation.intent,
    ]
      .join(" ")
      .toLowerCase();

    return (
      matchesFilter &&
      searchableText.includes(deferredLeadQuery.trim().toLowerCase())
    );
  });

  const urgentLead = conversations.find((conversation) => conversation.needsAttention);
  const attentionCount = conversations.filter(
    (conversation) => conversation.needsAttention,
  ).length;
  const agentHandlingCount = conversations.filter(
    (conversation) => conversation.agentMode === "agent",
  ).length;
  const humanHandlingCount = conversations.filter(
    (conversation) => conversation.agentMode === "human",
  ).length;
  const reservedCount = inventorySeeds.filter(
    (car) => car.status === "reserved",
  ).length;

  const sidebarStats = [
    {
      label: "Needs attention",
      value: String(attentionCount),
      note: "Qualified buyers waiting",
    },
    {
      label: "Agent handling",
      value: String(agentHandlingCount),
      note: "Conversations running on autopilot",
    },
    {
      label: "Owner active",
      value: String(humanHandlingCount),
      note: "Threads currently in manual takeover",
    },
    {
      label: "Reserved cars",
      value: String(reservedCount),
      note: "Availability synced across channels",
    },
  ];

  function handleSendReply() {
    if (!replyDraft.trim() || !selectedConversation) {
      return;
    }

    const nextMessage = {
      id: `owner-${Date.now()}`,
      role: "owner",
      channel: "dashboard",
      text: replyDraft.trim(),
      timestamp: "now",
    };

    startTransition(() => {
      setConversations((current) =>
        current.map((conversation) =>
          conversation.id === selectedConversation.id
            ? {
                ...conversation,
                agentMode: "human",
                needsAttention: false,
                waitingSince: "owner replied just now",
                messages: [...conversation.messages, nextMessage],
              }
            : conversation,
        ),
      );
      setReplyDraft("");
    });
  }

  function handleResumeAgent() {
    if (!selectedConversation) {
      return;
    }

    const nextMessage = {
      id: `system-${Date.now()}`,
      role: "system",
      channel: "dashboard",
      text: "Owner handed the conversation back to the AI agent.",
      timestamp: "now",
    };

    startTransition(() => {
      setConversations((current) =>
        current.map((conversation) =>
          conversation.id === selectedConversation.id
            ? {
                ...conversation,
                agentMode: "agent",
                messages: [...conversation.messages, nextMessage],
              }
            : conversation,
        ),
      );
    });
  }

  function handleOwnerAgentSubmit() {
    if (!agentDraft.trim()) {
      return;
    }

    const prompt = agentDraft.trim();
    startTransition(() => {
      setAgentMessages((current) => [
        ...current,
        { id: `user-${Date.now()}`, role: "owner", text: prompt },
        {
          id: `agent-${Date.now() + 1}`,
          role: "agent",
          text: generateAgentAnswer(prompt, conversations),
        },
      ]);
      setAgentDraft("");
    });
  }

  function focusUrgentLead() {
    if (!urgentLead) {
      return;
    }

    startTransition(() => {
      setActiveView("inbox");
      setLeadFilter("all");
      setSelectedId(urgentLead.id);
    });
  }

  return (
    <div className="dashboard-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-badge">V</div>
          <div>
            <p className="eyebrow">Owner control room</p>
            <h1>Vyapari Dashboard</h1>
          </div>
        </div>

        <nav className="nav-stack">
          {navItems.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${activeView === item.id ? "active" : ""}`}
              onClick={() => setActiveView(item.id)}
              type="button"
            >
              <div className="nav-copy">
                <span>{item.label}</span>
                <small>{item.note}</small>
              </div>
              {item.id === "inbox" ? (
                <strong className="nav-count">{attentionCount}</strong>
              ) : null}
            </button>
          ))}
        </nav>

        <section className="sidebar-card guide-card">
          <p className="eyebrow">Start here</p>
          <h2>Understand the dashboard in 30 seconds</h2>
          <div className="step-list">
            {onboardingSteps.map((step) => (
              <article key={step.id} className="step-card">
                <div className="step-number">{step.id}</div>
                <div className="step-body">
                  <strong>{step.title}</strong>
                  <p>{step.text}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="sidebar-card stats-card">
          {sidebarStats.map((card) => (
            <div key={card.label} className="mini-stat">
              <div>
                <span className="mini-stat-label">{card.label}</span>
                <small className="mini-stat-note">{card.note}</small>
              </div>
              <strong className="mini-stat-value">{card.value}</strong>
            </div>
          ))}
        </section>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Sharma Motors</p>
            <h2>
              {activeView === "inbox" && "See every lead and step in only when needed"}
              {activeView === "inventory" && "Know what is available, reserved, and moving"}
              {activeView === "insights" && "Understand demand without digging through chats"}
            </h2>
          </div>
          <div className="presence-row">
            <span className="presence-dot" />
            Agent online
          </div>
        </header>

        {activeView === "inbox" ? (
          <InboxView
            agentDraft={agentDraft}
            agentMessages={agentMessages}
            attentionCount={attentionCount}
            conversations={visibleConversations}
            onAgentDraftChange={setAgentDraft}
            onAgentSubmit={handleOwnerAgentSubmit}
            onJumpToUrgentLead={focusUrgentLead}
            onLeadFilterChange={setLeadFilter}
            onLeadQueryChange={setLeadQuery}
            onReplyDraftChange={setReplyDraft}
            onResumeAgent={handleResumeAgent}
            onSelectConversation={setSelectedId}
            onSendReply={handleSendReply}
            replyDraft={replyDraft}
            selectedConversation={selectedConversation}
            selectedId={selectedId}
            leadFilter={leadFilter}
            leadQuery={leadQuery}
            reservedCount={reservedCount}
          />
        ) : null}

        {activeView === "inventory" ? (
          <InventoryView inventory={inventorySeeds} />
        ) : null}

        {activeView === "insights" ? (
          <InsightsView
            conversations={conversations}
            insightCards={insightCards}
            inventory={inventorySeeds}
          />
        ) : null}
      </main>
    </div>
  );
}

function InboxView({
  agentDraft,
  agentMessages,
  attentionCount,
  conversations,
  leadFilter,
  leadQuery,
  onAgentDraftChange,
  onAgentSubmit,
  onJumpToUrgentLead,
  onLeadFilterChange,
  onLeadQueryChange,
  onReplyDraftChange,
  onResumeAgent,
  onSelectConversation,
  onSendReply,
  replyDraft,
  reservedCount,
  selectedConversation,
  selectedId,
}) {
  const leadScores = buildLeadScores(selectedConversation);

  return (
    <div className="stack-view">
      <section className="hero-card">
        <div className="hero-copy">
          <p className="eyebrow">Simple owner workflow</p>
          <h3>Start with the urgent lead, not the whole CRM.</h3>
          <p>
            Every WhatsApp conversation lands here. The agent handles the routine
            work, and you step in only when the buyer is warm, confused, or ready
            to close.
          </p>
          <div className="hero-actions">
            <button type="button" className="primary-button" onClick={onJumpToUrgentLead}>
              Open urgent lead
            </button>
            <button
              type="button"
              className="ghost-button"
              onClick={() => onLeadFilterChange("escalated")}
            >
              Show escalations
            </button>
          </div>
        </div>

        <WorkflowVisual />
      </section>

      <section className="summary-grid">
        <MetricTile
          kicker="Immediate"
          value={String(attentionCount)}
          note="Leads that need owner attention now"
        />
        <MetricTile
          kicker="Reserved"
          value={String(reservedCount)}
          note="Cars already protected from double-selling"
        />
        <MetricTile
          kicker="Top demand"
          value="6L-9L"
          note="Mid-range family SUVs are leading"
        />
        <MetricTile
          kicker="Quick win"
          value="Aman"
          note="Best chance to convert with finance guidance"
        />
      </section>

      <div className="grid-inbox">
        <section className="panel lead-column">
          <div className="panel-header">
            <div className="header-copy">
              <p className="eyebrow">1. Pick a lead</p>
              <h3>Lead queue</h3>
            </div>
            <span className="badge">{conversations.length} visible</span>
          </div>

          <input
            className="search-input"
            placeholder="Search by name, car, source..."
            value={leadQuery}
            onChange={(event) => onLeadQueryChange(event.target.value)}
          />

          <div className="chip-row">
            {filterChips.map((chip) => (
              <button
                key={chip}
                type="button"
                className={`chip ${leadFilter === chip ? "active" : ""}`}
                onClick={() => onLeadFilterChange(chip)}
              >
                {chip}
              </button>
            ))}
          </div>

          <div className="lead-list">
            {conversations.length ? (
              conversations.map((conversation) => (
                <button
                  key={conversation.id}
                  type="button"
                  className={`lead-card ${selectedId === conversation.id ? "selected" : ""}`}
                  onClick={() => onSelectConversation(conversation.id)}
                >
                  <div className="lead-card-top">
                    <div className="lead-card-heading">
                      <strong>{conversation.name}</strong>
                      <small>{conversation.source}</small>
                    </div>
                    <span className={`status-pill ${conversation.status}`}>
                      {conversation.status}
                    </span>
                  </div>
                  <p className="lead-card-summary">{conversation.summary}</p>
                  <div className="lead-card-footer">
                    <span>{conversation.vehicleInterest[0]}</span>
                    <span>{conversation.waitingSince}</span>
                  </div>
                  {conversation.needsAttention ? (
                    <div className="lead-focus-dot">Owner follow-up recommended</div>
                  ) : null}
                </button>
              ))
            ) : (
              <div className="empty-state">
                No leads match this filter. Try switching back to `all`.
              </div>
            )}
          </div>
        </section>

        <section className="panel conversation-column">
          <div className="panel-header conversation-header">
            <div className="header-copy">
              <p className="eyebrow">2. Continue the same thread</p>
              <h3>{selectedConversation.name}</h3>
            </div>
            <div className="channel-ribbon">
              <span>WhatsApp</span>
              <span>Dashboard</span>
            </div>
          </div>

          <div className="continuity-banner">
            This chat started on WhatsApp. The owner can reply here without
            forcing the customer to restart the conversation.
          </div>

          <div className="info-chip-row">
            <span className="info-chip">{selectedConversation.phone}</span>
            <span className="info-chip">{selectedConversation.source}</span>
            <span className="info-chip">{selectedConversation.budget}</span>
          </div>

          <div className="message-stream">
            {selectedConversation.messages.map((message) => (
              <article
                key={message.id}
                className={`message-bubble ${message.role} ${message.role === "system" ? "system" : ""}`}
              >
                {message.role !== "system" ? (
                  <div className="message-label">
                    <span>{message.role}</span>
                    <small>{message.channel}</small>
                  </div>
                ) : null}
                <p>{message.text}</p>
                <time>{message.timestamp}</time>
              </article>
            ))}
          </div>

          <div className="reply-box">
            <div className="reply-actions">
              <span className={`mode-pill ${selectedConversation.agentMode}`}>
                {selectedConversation.agentMode === "human"
                  ? "Owner takeover active"
                  : "Agent active"}
              </span>
              <button type="button" className="ghost-button" onClick={onResumeAgent}>
                Resume agent
              </button>
            </div>

            <textarea
              rows="3"
              placeholder="Reply as the owner from the dashboard..."
              value={replyDraft}
              onChange={(event) => onReplyDraftChange(event.target.value)}
            />
            <button type="button" className="primary-button" onClick={onSendReply}>
              Send owner reply
            </button>
          </div>
        </section>

        <section className="panel intelligence-column">
          <div className="panel-header">
            <div className="header-copy">
              <p className="eyebrow">3. Let the AI explain what matters</p>
              <h3>Next move for this lead</h3>
            </div>
          </div>

          <div className="summary-card">
            <span
              className={`status-pill ${selectedConversation.needsAttention ? "escalated" : "warm"}`}
            >
              {selectedConversation.needsAttention
                ? "needs owner now"
                : "agent can continue"}
            </span>
            <p>{selectedConversation.summary}</p>
            <ul className="detail-list">
              <li>Intent: {selectedConversation.intent}</li>
              <li>Objection: {selectedConversation.objection}</li>
              <li>Recommended move: {selectedConversation.recommendation}</li>
            </ul>
          </div>

          <div className="score-grid">
            {leadScores.map((score) => (
              <ScoreBar key={score.label} score={score} />
            ))}
          </div>

          <div className="oracle-panel">
            <div className="oracle-header">
              <h4>Ask the owner agent</h4>
              <span>Natural language answers, not dashboard digging</span>
            </div>

            <div className="oracle-messages">
              {agentMessages.map((message) => (
                <div
                  key={message.id}
                  className={`oracle-bubble ${message.role === "owner" ? "owner" : "agent"}`}
                >
                  {message.text}
                </div>
              ))}
            </div>

            <textarea
              rows="3"
              placeholder="Ask: Which lead is closest to buying today?"
              value={agentDraft}
              onChange={(event) => onAgentDraftChange(event.target.value)}
            />
            <button type="button" className="secondary-button" onClick={onAgentSubmit}>
              Ask owner agent
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}

function InventoryView({ inventory }) {
  const statusItems = [
    {
      label: "Available",
      value: inventory.filter((item) => item.status === "available").length,
      color: "#2b7a4b",
    },
    {
      label: "Reserved",
      value: inventory.filter((item) => item.status === "reserved").length,
      color: "#b34e35",
    },
    {
      label: "Sold",
      value: inventory.filter((item) => item.status === "sold").length,
      color: "#b07b17",
    },
  ];

  const mostAskedCars = [...inventory]
    .sort((left, right) => right.inquiries - left.inquiries)
    .map((item) => ({
      label: item.name,
      value: item.inquiries,
      hint: `${item.price} | ${item.status}`,
    }));

  return (
    <div className="stack-view">
      <section className="hero-card">
        <div className="hero-copy">
          <p className="eyebrow">Inventory control</p>
          <h3>Keep stock simple, visible, and synced across channels.</h3>
          <p>
            The owner should be able to see what is available, what is already
            reserved, and which cars are attracting attention without learning a
            complicated back office.
          </p>
          <div className="hero-actions">
            <button type="button" className="primary-button">
              Add vehicle
            </button>
            <button type="button" className="ghost-button">
              Upload PDF or sheet
            </button>
          </div>
        </div>

        <StatusRing items={statusItems} title="Stock status" />
      </section>

      <div className="inventory-layout">
        <section className="panel inventory-table-panel">
          <div className="panel-header">
            <div className="header-copy">
              <p className="eyebrow">Live inventory</p>
              <h3>Cars in catalogue</h3>
            </div>
          </div>

          <div className="inventory-table">
            {inventory.map((item) => (
              <div key={item.id} className="inventory-row">
                <div className="row-main">
                  <div>
                    <strong>{item.name}</strong>
                    <p className="row-sub">{item.source}</p>
                  </div>
                  <span className={`status-pill ${item.status}`}>{item.status}</span>
                </div>
                <div className="row-main">
                  <strong>{item.price}</strong>
                  <span>{item.inquiries} inquiries</span>
                </div>
                <div className="row-actions">
                  <button type="button" className="ghost-button small">
                    Update price
                  </button>
                  <button type="button" className="ghost-button small">
                    Mark sold
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="chart-stack">
          <section className="panel chart-panel">
            <div className="chart-header">
              <div className="header-copy">
                <p className="eyebrow">Visuals</p>
                <h3>Most asked cars</h3>
              </div>
            </div>
            <HorizontalBars items={mostAskedCars} />
          </section>

          <section className="panel chart-panel">
            <div className="chart-header">
              <div className="header-copy">
                <p className="eyebrow">Demand by budget</p>
                <h3>Where current demand sits</h3>
              </div>
            </div>
            <VerticalBars items={priceBandDemand} />
          </section>
        </section>
      </div>
    </div>
  );
}

function InsightsView({ conversations, insightCards, inventory }) {
  const escalatedCount = conversations.filter((lead) => lead.needsAttention).length;
  const reservedCount = inventory.filter((car) => car.status === "reserved").length;

  return (
    <div className="stack-view">
      <section className="insight-grid">
        {insightCards.map((card) => (
          <article key={card.label} className="insight-card">
            <p>{card.label}</p>
            <strong>{card.value}</strong>
            <span>{card.note}</span>
          </article>
        ))}
      </section>

      <div className="insight-layout">
        <section className="panel chart-panel">
          <div className="chart-header">
            <div className="header-copy">
              <p className="eyebrow">Lead trend</p>
              <h3>Weekly lead flow</h3>
            </div>
          </div>
          <VerticalBars items={weeklyLeadTrend} compact />
        </section>

        <section className="panel chart-panel">
          <div className="chart-header">
            <div className="header-copy">
              <p className="eyebrow">Lead funnel</p>
              <h3>From inquiry to conversion</h3>
            </div>
          </div>
          <div className="funnel-list">
            {leadStageData.map((item) => (
              <div key={item.label} className="funnel-row">
                <div className="bar-copy">
                  <strong>{item.label}</strong>
                  <small>{item.note}</small>
                </div>
                <div className="funnel-bar">
                  <div
                    className="bar-fill"
                    style={{ width: `${item.value}%`, background: item.color }}
                  />
                </div>
                <span className="bar-value">{item.display}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="insight-layout">
        <section className="panel chart-panel">
          <div className="chart-header">
            <div className="header-copy">
              <p className="eyebrow">Price range demand</p>
              <h3>What buyers are searching for</h3>
            </div>
          </div>
          <HorizontalBars items={priceBandDemand} />
        </section>

        <section className="panel chart-panel">
          <div className="chart-header">
            <div className="header-copy">
              <p className="eyebrow">Lead sources</p>
              <h3>Which channels are feeding demand</h3>
            </div>
          </div>
          <HorizontalBars items={sourceBreakdown} />
        </section>
      </div>

      <section className="panel recommendations-panel">
        <div className="panel-header">
          <div className="header-copy">
            <p className="eyebrow">AI recommendations</p>
            <h3>What the owner should do next</h3>
          </div>
        </div>

        <div className="recommendation-list">
          <div className="recommendation-item">
            <strong>Jump into Aman now</strong>
            <p>
              Strong close potential. Finance concern is the last blocker and the
              customer already asked for Rajesh by name.
            </p>
          </div>
          <div className="recommendation-item">
            <strong>Push 6L-9L SUVs in the next reel</strong>
            <p>
              Current demand is clustered in the mid-range family SUV segment.
            </p>
          </div>
          <div className="recommendation-item">
            <strong>Add a delivery FAQ</strong>
            <p>
              Customers asked about delivery and location repeatedly this week.
            </p>
          </div>
        </div>

        <div className="signal-bar">
          <div>
            <span>Escalations pending</span>
            <strong>{escalatedCount}</strong>
          </div>
          <div>
            <span>Reserved vehicles</span>
            <strong>{reservedCount}</strong>
          </div>
          <div>
            <span>Cars with highest comparison traffic</span>
            <strong>Nexon, Brezza</strong>
          </div>
        </div>
      </section>
    </div>
  );
}

function WorkflowVisual() {
  return (
    <div className="workflow-visual" aria-hidden="true">
      <div className="flow-node">
        <span className="step-number">1</span>
        <div>
          <strong className="flow-node-title">Customer asks on WhatsApp</strong>
          <p className="flow-node-note">Agent replies instantly and qualifies intent.</p>
        </div>
      </div>
      <div className="workflow-line" />
      <div className="flow-node">
        <span className="step-number">2</span>
        <div>
          <strong className="flow-node-title">Dashboard shows only what matters</strong>
          <p className="flow-node-note">Escalations, summaries, and the next move appear clearly.</p>
        </div>
      </div>
      <div className="workflow-line" />
      <div className="flow-node">
        <span className="step-number">3</span>
        <div>
          <strong className="flow-node-title">Owner steps in without breaking context</strong>
          <p className="flow-node-note">Same thread, same customer, no restart needed.</p>
        </div>
      </div>
    </div>
  );
}

function MetricTile({ kicker, value, note }) {
  return (
    <article className="summary-tile">
      <p className="tile-kicker">{kicker}</p>
      <strong className="tile-value">{value}</strong>
      <span className="tile-note">{note}</span>
    </article>
  );
}

function ScoreBar({ score }) {
  return (
    <div className="score-row">
      <div className="score-label">
        <span>{score.label}</span>
        <strong>{score.value}%</strong>
      </div>
      <div className="score-track">
        <div
          className="score-fill"
          style={{ width: `${score.value}%`, background: score.color }}
        />
      </div>
    </div>
  );
}

function HorizontalBars({ items }) {
  const maxValue = Math.max(...items.map((item) => item.value), 1);

  return (
    <div className="horizontal-bars">
      {items.map((item) => (
        <div key={item.label} className="bar-row">
          <div className="bar-copy">
            <strong>{item.label}</strong>
            {item.hint ? <small>{item.hint}</small> : null}
          </div>
          <div className="bar-track">
            <div
              className="bar-fill"
              style={{
                width: `${(item.value / maxValue) * 100}%`,
                background: item.color ?? "#d86f31",
              }}
            />
          </div>
          <span className="bar-value">{item.display ?? item.value}</span>
        </div>
      ))}
    </div>
  );
}

function VerticalBars({ items, compact = false }) {
  const maxValue = Math.max(...items.map((item) => item.value), 1);

  return (
    <div className={`vertical-bars ${compact ? "compact" : ""}`}>
      <div className="bars">
        {items.map((item) => (
          <div key={item.label} className="bars-col">
            <span className="bars-value">{item.display ?? item.value}</span>
            <div
              className="bar-fill"
              style={{
                height: `${(item.value / maxValue) * 100}%`,
                background: item.color ?? "#2b7a4b",
              }}
            />
            <span className="bars-label">{item.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function StatusRing({ items, title }) {
  const total = items.reduce((sum, item) => sum + item.value, 0) || 1;
  let cursor = 0;

  const segments = items
    .map((item) => {
      const slice = (item.value / total) * 360;
      const start = cursor;
      const end = cursor + slice;
      cursor = end;
      return `${item.color} ${start}deg ${end}deg`;
    })
    .join(", ");

  return (
    <div className="chart-card ring-wrap">
      <div className="chart-header">
        <div className="header-copy">
          <p className="eyebrow">Visual</p>
          <h3>{title}</h3>
        </div>
      </div>
      <div className="status-ring" style={{ background: `conic-gradient(${segments})` }}>
        <div className="ring-center">
          <strong>{total}</strong>
          <span>cars</span>
        </div>
      </div>
      <div className="legend-list">
        {items.map((item) => (
          <div key={item.label} className="mini-stat">
            <div className="mini-stat-label">
              <span
                className="legend-swatch"
                style={{ background: item.color }}
              />
              {item.label}
            </div>
            <strong className="mini-stat-value">{item.value}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function buildLeadScores(conversation) {
  const buyingIntent =
    conversation.status === "hot" ? 88 : conversation.status === "warm" ? 72 : 54;
  const urgency = conversation.needsAttention ? 93 : conversation.agentMode === "human" ? 70 : 46;
  const clarity =
    conversation.objection.includes("high") || conversation.objection.includes("confidence")
      ? 67
      : 79;

  return [
    { label: "Buying intent", value: buyingIntent, color: "#2b7a4b" },
    { label: "Owner urgency", value: urgency, color: "#b34e35" },
    { label: "Close clarity", value: clarity, color: "#d86f31" },
  ];
}

function generateAgentAnswer(prompt, conversations) {
  const lowerPrompt = prompt.toLowerCase();

  if (lowerPrompt.includes("hot lead") || lowerPrompt.includes("closest to buying")) {
    return "Aman is the best immediate close. He is qualified, price-sensitive, and already asked to speak with Rajesh directly.";
  }

  if (lowerPrompt.includes("financing")) {
    return "Two active leads have financing intent. Aman is the strongest one, and Neha is a good recovery candidate if you position the Punch with EMI.";
  }

  if (lowerPrompt.includes("reel") || lowerPrompt.includes("post")) {
    return "Double down on the 6L-9L SUV segment. Nexon and Brezza are driving the most conversation volume right now.";
  }

  if (lowerPrompt.includes("inventory") || lowerPrompt.includes("reserved")) {
    const reserved = conversations
      .flatMap((conversation) => conversation.vehicleInterest)
      .find((vehicle) => vehicle.includes("Nexon"));
    return `${reserved ?? "Nexon XZ+"} is the most sensitive stock item right now. Keep its hold/reserve state consistent across channels.`;
  }

  return "Right now I would focus on fast response time, finance-assisted recovery, and keeping the owner takeover flow frictionless for warm leads.";
}

export default App;
