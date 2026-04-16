# Vyapari Agent: Architecture Synthesis -- Customer Context, Relay, and Batch Operations

**Date:** April 15, 2026
**Context:** Design decision on how to implement the customer-agent conversation, owner-agent conversation, relay/hijack, and batch follow-ups. Synthesized from parallel research on OpenAI Agents SDK and LangGraph.

---

## The Core Architecture Question

```
                    WhatsApp (single number)
                           |
                      Message Router
                      (role lookup)
                     /              \
            Customer msg           Owner/SDR msg
                |                       |
         Customer Agent            Owner Agent
         (per-customer             (per-staff
          conversation              conversation
          thread)                   thread)
                |                       |
         [search, browse,         [analytics, catalogue,
          compare, escalate]       relay, staff mgmt]
                                        |
                                   open_session
                                        |
                                  HOW DOES THIS
                                  AGENT ACCESS
                                  THE CUSTOMER'S
                                  CONVERSATION?
```

Specific questions answered:
1. Are these two separate agent instances?
2. Where does conversation history live?
3. During relay -- who is the agent?
4. How does batch follow-up ("kal ki sab leads se followup karo") work?

---

## Answer 1: Three Separate Things (Not Two Agents, Not One Agent)

```
WhatsApp Webhook (PyWa)
         |
    MESSAGE ROUTER  <-- Pure Python, NOT an agent
    (role lookup,        Checks: Staff table, conversation state,
     state check)        relay sessions, /login detection
         |
    +----+----+----+
    |         |    |
    v         v    v
CUSTOMER   OWNER  RELAY
 AGENT     AGENT  MODE
    |         |    |
  per-       per-  no agent --
  customer   staff just forward
  session    session  messages
```

**1. Message Router** -- Not an agent. Pure Python function. On every incoming webhook:
- Look up `wa_id` in Staff table -> resolve role
- Check conversation state (ACTIVE, ESCALATED, RELAY_ACTIVE)
- If RELAY_ACTIVE + no prefix -> bypass agents entirely, forward message
- If customer -> load their session, run Customer Agent
- If staff -> load their session, run Owner/SDR Agent

**2. Customer Agent** -- One agent definition, many sessions. Each customer gets their own isolated session (keyed by `wa_id`). The agent doesn't know about other customers. It just knows the catalogue, FAQs, and THIS customer's history.

**3. Owner/SDR Agent** -- Separate agent with different tools. Has its own session per staff member. When the owner says "ertiga wale se baat karna hai", the `open_session` tool queries the DB, loads the target customer's conversation history, and presents it as a summary. It does NOT hand off to the Customer Agent.

**4. Relay Mode** -- No agent runs. The router sees RELAY_ACTIVE, checks for `/` prefix, and either forwards the message to the customer or processes an agent command. This is just if/else logic.

---

## Answer 2: Sessions -- Per-Customer Isolation

Both frameworks handle this the same way:

**OpenAI Agents SDK:**
```python
session_id = f"customer_{wa_id}"
session = PostgresSession(session_id, db_pool)
result = await Runner.run(customer_agent, input=message, session=session)
```

**LangGraph:**
```python
thread_id = f"customer_{wa_id}"
config = {"configurable": {"thread_id": thread_id}}
result = graph.invoke({"messages": [HumanMessage(msg)]}, config=config)
```

Customer A has session `customer_919876543210`. Customer B has `customer_919123456789`. Completely isolated. The agent sees only their own history.

The owner/SDR has session `staff_919999888777`. Also isolated. Their session tracks their own conversation with the agent (analytics queries, catalogue changes, etc.) -- NOT customer conversations.

---

## Answer 3: How the Owner Agent Accesses a Customer's Conversation

The `open_session` tool reads from the customer's session/DB directly. The customer's agent instance is never involved.

**OpenAI Agents SDK implementation:**

```python
@function_tool
async def open_session(
    ctx: RunContextWrapper[StaffContext],
    query: str
) -> str:
    """Open a relay session with a customer matching the query."""
    # 1. Search active leads in PostgreSQL
    leads = await db.search_leads(query, business_id=ctx.context.business_id)
    
    if len(leads) == 0:
        return "No matching customers found."
    
    if len(leads) > 1:
        # Format list for owner to pick from
        return format_lead_list(leads)  # "1. Ramesh (Ertiga)  2. Sunil (Ertiga)"
    
    # 2. Load the customer's conversation history from THEIR session
    customer = leads[0]
    customer_session = PostgresSession(f"customer_{customer.wa_id}", db_pool)
    history = await customer_session.get_items()
    
    # 3. Generate summary from history (could be LLM call or just last N messages)
    summary = await generate_conversation_summary(history)
    last_5 = format_last_n_messages(history, n=5)
    
    # 4. Create RelaySession record in DB
    await db.create_relay_session(
        staff_id=ctx.context.staff_id,
        customer_id=customer.id,
        conversation_id=customer.active_conversation_id
    )
    
    # 5. Update conversation state
    await db.update_conversation_state(
        customer.active_conversation_id, "RELAY_ACTIVE"
    )
    
    return f"""Session with {customer.name} started.
Everything you type goes to the customer.
Use /done when finished.

--- SUMMARY ---
{summary}

--- LAST 5 MESSAGES ---
{last_5}"""
```

**LangGraph equivalent:**

```python
def open_session_tool(state, config):
    customer_config = {"configurable": {"thread_id": f"customer_{customer_id}"}}
    customer_state = customer_graph.get_state(customer_config)
    messages = customer_state.values.get("messages", [])
    # ... format summary, create relay session ...
```

---

## Answer 4: How Relay Mode Works (No Agent)

During RELAY_ACTIVE, the message router does this:

```python
# In the FastAPI webhook handler (simplified)

async def handle_message(wa_id: str, text: str):
    role = await get_role(wa_id)  # customer / owner / sdr / unknown
    
    if role == "customer":
        conversation = await get_conversation(wa_id)
        
        if conversation.state == "RELAY_ACTIVE":
            # NO AGENT RUNS. Just forward.
            relay = await get_active_relay(conversation.id)
            staff_wa_id = relay.staff_wa_id
            
            # Forward customer message to the staff member
            await wa.send_message(
                to=staff_wa_id,
                text=f"[{conversation.customer_name}]: {text}"
            )
            # Store the message
            await store_message(conversation.id, role="customer", content=text)
            return
        
        # Normal: run Customer Agent
        session = PostgresSession(f"customer_{wa_id}", db_pool)
        result = await Runner.run(customer_agent, text, session=session, context=ctx)
        await wa.send_message(to=wa_id, text=result.final_output)
    
    elif role in ("owner", "sdr"):
        relay = await get_active_relay_for_staff(wa_id)
        
        if relay and not text.startswith("/"):
            # RELAY MODE: forward to customer. No agent.
            await wa.send_message(to=relay.customer_wa_id, text=text)
            await store_message(relay.conversation_id, role=role, content=text)
            await update_relay_last_active(relay.id)
            return
        
        if relay and text.startswith("/"):
            # Agent command during relay
            if text == "/done":
                await close_relay_session(relay.id)
                await wa.send_message(to=wa_id, text="Session closed. Agent resumed.")
                return
            # ... other /commands ...
        
        # No relay: run Owner/SDR Agent
        session = PostgresSession(f"staff_{wa_id}", db_pool)
        result = await Runner.run(owner_agent, text, session=session, context=staff_ctx)
        await wa.send_message(to=wa_id, text=result.final_output)
```

The agents don't know about relay. The router handles it before the agent is ever called.

---

## Answer 5: How "Kal Ki Sab Leads Se Followup Karo" Works

Owner says this to the Owner Agent. The agent calls a `batch_followup` tool. The tool:

1. Queries DB for yesterday's leads
2. For each lead, loads their conversation session
3. Runs a lightweight follow-up agent per customer in parallel
4. Sends personalized messages via WhatsApp (template if outside 24hr window)

**OpenAI Agents SDK implementation:**

```python
@function_tool
async def batch_followup(
    ctx: RunContextWrapper[StaffContext],
    date: str = "yesterday",
    status_filter: str = "warm,hot"
) -> str:
    """Follow up with leads from a specific date."""
    leads = await db.get_leads_by_date(date, status_filter.split(","))
    
    followup_agent = Agent(
        name="Follow-up Writer",
        instructions="""Generate a short, personalized WhatsApp follow-up message.
        Use Hinglish. Reference the specific car they asked about.
        Keep it under 3 sentences. Be warm, not pushy."""
    )
    
    async def generate_one(customer):
        session = PostgresSession(f"customer_{customer.wa_id}", db_pool)
        history = await session.get_items()
        
        prompt = f"""Customer: {customer.name}
Car interest: {customer.interested_car}
Lead temperature: {customer.lead_status}
Last active: {customer.last_active}

Conversation summary:
{summarize(history)}

Write a follow-up message."""
        
        result = await Runner.run(followup_agent, prompt)
        return (customer, result.final_output)
    
    # Fan out: all customers in parallel
    results = await asyncio.gather(*(generate_one(c) for c in leads))
    
    # Send each follow-up
    sent_count = 0
    for customer, message in results:
        if is_within_24hr_window(customer.last_message_at):
            await wa.send_message(to=customer.wa_id, text=message)
        else:
            await wa.send_template(
                to=customer.wa_id,
                template="car_followup_day1",
                params=[customer.name, customer.interested_car]
            )
        sent_count += 1
    
    return f"Sent {sent_count} personalized follow-ups."
```

**LangGraph equivalent (using Send() for parallel fan-out):**

```python
def fan_out_to_customers(state: BatchState):
    return [Send("generate_followup", {"customer_id": cid}) 
            for cid in state["customer_ids"]]
```

---

## Framework Comparison

| Factor | OpenAI Agents SDK | LangGraph |
|--------|------------------|-----------|
| Hackathon alignment | Codex hackathon, OpenAI judges | Neutral |
| Setup complexity | `pip install openai-agents` | `pip install langgraph langgraph-supervisor` + checkpointer packages |
| Session management | Built-in `SQLiteSession`, custom `PostgresSession` (implement `SessionABC`) | Built-in `PostgresSaver` (more mature) |
| Per-customer isolation | Session ID per customer | Thread ID per customer |
| Agent tools | `@function_tool` decorator, clean | `@tool` decorator, similar |
| Batch fan-out | `asyncio.gather()` (simple, manual) | `Send()` API (built-in, more structured) |
| Human-in-the-loop | `needs_approval=True` + `RunState` serialization | `interrupt()` + `Command(resume=...)` |
| Cross-thread inspection | `session.get_items()` | `graph.get_state(config)` |
| Agent handoffs | `handoff()` function | `Command(graph=Command.PARENT)` |
| Maturity | Newer (but actively developed, 20.7k stars) | Mature (battle-tested in production) |

**Recommendation: OpenAI Agents SDK.** It's simpler, aligns with the hackathon, and the relay system doesn't need LangGraph's graph complexity -- it's application-layer routing. The batch follow-up with `asyncio.gather()` is 5 lines of code. LangGraph's `Send()` is more structured but overkill for this.

The only thing LangGraph does better here is `PostgresSaver` (production-ready, one line). With the Agents SDK, you'd implement `PostgresSession` yourself (~30 lines). Worth the trade-off for hackathon simplicity.

---

## Key Insight: What The Relay Is NOT

Both frameworks agree: **the relay/hijack system is NOT an agent handoff.**

In agent frameworks, a handoff transfers control between two LLM agents. But in Vyapari's relay, the owner (a human) takes over a customer conversation. This is a **message routing change at the application layer**, not an agent orchestration pattern:

1. Owner says "ertiga wale se baat karna hai" to the Owner Agent
2. Owner Agent calls `open_session` tool, which changes conversation state in the DB to `RELAY_ACTIVE`
3. The FastAPI message router detects `RELAY_ACTIVE` state for subsequent messages
4. Customer messages are forwarded to the owner (not to the Customer Agent)
5. Owner messages (without `/` prefix) are forwarded to the customer via WhatsApp
6. Owner types `/done` -> router changes state back to `ACTIVE`, Customer Agent resumes

The Agent SDK's human-in-the-loop (`needs_approval` + `RunState` serialization) could handle the approval step for sensitive owner tools (like `mark_sold` or `broadcast_message`), but the relay itself is simpler -- it is a state machine in PostgreSQL that the router checks on every incoming message.

---

## Summary Table

| Question | Answer |
|----------|--------|
| Are Customer Agent and Owner Agent separate? | **Yes.** Different agent instances, different tools, different sessions. |
| Where does conversation history live? | **Per-customer session** (keyed by wa_id). Per-staff session for owner/SDR conversations with the agent. |
| How does Owner Agent access customer history? | **`open_session` tool** reads from the customer's session directly. No handoff. |
| During relay, who is the agent? | **No agent.** Router bypasses agents, forwards messages raw. |
| How does batch follow-up work? | **`asyncio.gather()`** over a lightweight follow-up agent, one run per customer, each with that customer's history loaded. |
| Is the relay an agent handoff? | **No.** It's a state flag in PostgreSQL. Router checks it on every message. |
