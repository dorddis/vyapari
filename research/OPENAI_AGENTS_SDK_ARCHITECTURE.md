# OpenAI Agents SDK: Multi-Agent Architecture Research

**Date:** April 15, 2026
**Context:** Vyapari Agent hackathon -- researching how to implement customer-facing agent + owner agent with relay/hijack and batch follow-ups using OpenAI Agents SDK

---

## 1. SDK Architecture Overview

The OpenAI Agents SDK (`pip install openai-agents`) is a lightweight Python framework (20.7k+ GitHub stars, latest release April 9, 2026) built around eight core primitives:

**Core primitives:** Agent, Runner, Tools, Handoffs, Guardrails, Sessions, Human-in-the-Loop, Tracing

**Basic pattern:**

```python
from agents import Agent, Runner

agent = Agent(name="Assistant", instructions="You are a helpful assistant")
result = Runner.run_sync(agent, "Your task here")
print(result.final_output)
```

The SDK is provider-agnostic and supports OpenAI Responses API, Chat Completions API, and 100+ other LLMs.

---

## 2. Agent Handoffs (transfer_to_X)

Handoffs are the primary mechanism for transferring control between agents. Each handoff is represented as a tool to the LLM. If agent A has a handoff to an agent named "Refund Agent", the LLM sees a tool called `transfer_to_refund_agent`.

**Key code patterns:**

```python
from agents import Agent, handoff, RunContextWrapper
from pydantic import BaseModel

# Pattern 1: Direct handoff (simplest)
billing_agent = Agent(name="Billing agent")
refund_agent = Agent(name="Refund agent")
triage_agent = Agent(
    name="Triage agent",
    handoffs=[billing_agent, handoff(refund_agent)],
)

# Pattern 2: Handoff with callback + typed input
class EscalationData(BaseModel):
    reason: str

async def on_handoff(ctx: RunContextWrapper[None], input_data: EscalationData):
    print(f"Escalation agent called with reason: {input_data.reason}")

handoff_obj = handoff(
    agent=refund_agent,
    on_handoff=on_handoff,
    input_type=EscalationData,
)

# Pattern 3: Handoff with input filter (controls what history the next agent sees)
from agents.extensions import handoff_filters
handoff_obj = handoff(
    agent=refund_agent,
    input_filter=handoff_filters.remove_all_tools,
)
```

**Conversation history during handoff:** By default, the receiving agent sees the ENTIRE previous conversation history. You can control this with:
- `input_filter` -- a function receiving `HandoffInputData` that returns modified `HandoffInputData`
- `RunConfig.nest_handoff_history` (opt-in beta) -- collapses prior transcript into a `<CONVERSATION HISTORY>` summary block
- `RunConfig.handoff_history_mapper` -- custom function to replace the generated summary

**Critical for Vyapari architecture:** Handoffs are ONE-WAY. The new agent takes over completely. There is no built-in "return to previous agent" mechanism. You must set up handoffs in both directions (agent A -> agent B AND agent B -> agent A) if you want round-trip transfers. The Codex multi-agent demo shows this pattern explicitly:

```python
project_manager_agent = Agent(
    name="Project Manager",
    handoffs=[designer_agent, frontend_developer_agent, backend_developer_agent, tester_agent],
)
# Each specialist hands back to PM:
designer_agent.handoffs = [project_manager_agent]
frontend_developer_agent.handoffs = [project_manager_agent]
```

---

## 3. Two Orchestration Patterns: Handoffs vs. Agents-as-Tools

The SDK supports two distinct multi-agent patterns, and **Vyapari's architecture needs BOTH**.

### Pattern A: Handoffs (triage/routing)

The triage agent routes the conversation to a specialist. The specialist BECOMES the active agent for the rest of the turn. The specialist speaks directly to the user.

```python
triage_agent = Agent(
    name="Triage agent",
    instructions="Route to booking or refund agent based on user intent.",
    handoffs=[booking_agent, refund_agent],
)
```

**Use for:** Message router deciding between Customer Agent and Owner Agent.

### Pattern B: Agents as Tools (supervisor/manager)

A manager agent keeps control and calls specialist agents through `Agent.as_tool()`. The manager narrates the final response. Sub-agents do NOT take over the conversation.

```python
booking_agent = Agent(...)
refund_agent = Agent(...)

customer_facing_agent = Agent(
    name="Customer-facing agent",
    instructions="Handle all direct user communication.",
    tools=[
        booking_agent.as_tool(
            tool_name="booking_expert",
            tool_description="Handles booking questions and requests.",
        ),
        refund_agent.as_tool(
            tool_name="refund_expert",
            tool_description="Handles refund questions and requests.",
        ),
    ],
)
```

**Key differences:**

| Feature | Handoffs | Agents-as-Tools |
|---------|----------|-----------------|
| Who speaks to user? | Specialist agent | Manager agent |
| Control transfer | Full transfer | Manager keeps control |
| Conversation state | Full history passed | Sub-agent gets scoped input |
| Best for | Routing/triage | Coordinated multi-skill tasks |

---

## 4. Conversation/Thread Management Per Customer

**This is the most important section for the architecture.** The SDK provides multiple mechanisms for managing per-customer conversation state.

### Built-in Session Types

| Type | Best For | Install |
|------|----------|---------|
| `SQLiteSession` | Local dev, simple apps | Built-in |
| `AsyncSQLiteSession` | Async SQLite with aiosqlite | Built-in |
| `RedisSession` | Distributed/production | `pip install openai-agents-redis` |
| `SQLAlchemySession` | Production with existing DBs | Community |
| `DaprSession` | Cloud-native with Dapr | Community |
| `OpenAIConversationsSession` | OpenAI-hosted storage | Built-in |
| `EncryptedSession` | Wrapper adding encryption + TTL | Built-in |

### Per-Customer Session Pattern (CRITICAL for Vyapari)

```python
from agents import Agent, Runner, SQLiteSession

agent = Agent(name="Sales Agent", instructions="...")

# Each customer gets their own session_id
# Same DB file, different session IDs = isolated histories
session_ramesh = SQLiteSession("customer_ramesh_9876543210", "conversations.db")
session_priya  = SQLiteSession("customer_priya_9123456789", "conversations.db")

# First turn for Ramesh
result = await Runner.run(agent, "Creta ka price kya hai?", session=session_ramesh)

# First turn for Priya (completely independent history)
result = await Runner.run(agent, "Nexon available hai?", session=session_priya)

# Second turn for Ramesh (session auto-includes prior history)
result = await Runner.run(agent, "EMI kitna aayega?", session=session_ramesh)
```

### Session Operations (Read/Write History)

```python
session = SQLiteSession("customer_123", "conversations.db")

# Read all conversation items
items = await session.get_items()

# Add items manually (e.g., inject context)
await session.add_items([{"role": "user", "content": "Hello"}])

# Pop last item
last_item = await session.pop_item()

# Clear entire session
await session.clear_session()
```

### Multiple Agents Sharing Same Session

Different agents can access the same customer session. This is useful for the relay system where the Owner Agent needs to see the customer conversation:

```python
customer_agent = Agent(name="Customer Agent", tools=[...customer_tools...])
owner_agent = Agent(name="Owner Agent", tools=[...owner_tools...])

# Both see the same conversation history for this customer
session = SQLiteSession("customer_ramesh_9876543210")
result1 = await Runner.run(customer_agent, customer_message, session=session)
# Later, owner wants to see what happened:
items = await session.get_items()  # Full conversation history
```

### Manual History Management (Alternative to Sessions)

```python
# First turn
result = await Runner.run(agent, "What city is the Golden Gate Bridge in?")

# Second turn - manually chain history
new_input = result.to_input_list() + [{"role": "user", "content": "What state?"}]
result = await Runner.run(agent, new_input)
```

### Custom Session (for PostgreSQL)

Since Vyapari uses PostgreSQL, you would implement `SessionABC`:

```python
from agents.memory.session import SessionABC
from agents.items import TResponseInputItem
from typing import List
import json

class PostgresSession(SessionABC):
    def __init__(self, session_id: str, db_pool):
        self.session_id = session_id
        self.db_pool = db_pool

    async def get_items(self, limit: int | None = None) -> List[TResponseInputItem]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT item FROM conversation_items WHERE session_id=$1 ORDER BY created_at",
                self.session_id
            )
        items = [json.loads(r['item']) for r in rows]
        return items[-limit:] if limit else items

    async def add_items(self, items: List[TResponseInputItem]) -> None:
        async with self.db_pool.acquire() as conn:
            for item in items:
                await conn.execute(
                    "INSERT INTO conversation_items (session_id, item) VALUES ($1, $2)",
                    self.session_id, json.dumps(item)
                )

    async def pop_item(self) -> TResponseInputItem | None:
        # Remove and return last item
        ...

    async def clear_session(self) -> None:
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM conversation_items WHERE session_id=$1", self.session_id
            )
```

---

## 5. Context/Memory Management (RunContextWrapper)

`RunContextWrapper[T]` is the dependency injection mechanism. Your custom context object is passed to `Runner.run()` and is accessible to all tools, hooks, and callbacks -- but it is **NOT sent to the LLM**. It is purely local state.

### Per-Customer Context Pattern

```python
from dataclasses import dataclass
from agents import Agent, RunContextWrapper, Runner, function_tool

@dataclass
class CustomerContext:
    customer_id: str
    name: str
    phone: str
    lead_temperature: str  # cold/warm/hot
    interested_cars: list[str]
    conversation_state: str  # ACTIVE/ESCALATED/RELAY_ACTIVE

@function_tool
async def search_catalogue(wrapper: RunContextWrapper[CustomerContext], query: str) -> str:
    """Search the car catalogue."""
    customer = wrapper.context
    print(f"Searching for {customer.name} (temp: {customer.lead_temperature})")
    # ... database query ...
    return "Results: ..."

@function_tool
async def request_escalation(wrapper: RunContextWrapper[CustomerContext], reason: str) -> str:
    """Escalate this conversation to staff."""
    ctx = wrapper.context
    ctx.conversation_state = "ESCALATED"  # Mutate context!
    # ... send notification ...
    return f"Escalated: {reason}"

customer_agent = Agent[CustomerContext](
    name="Sales Agent",
    instructions="You are a car sales agent...",
    tools=[search_catalogue, request_escalation],
)

# Run with customer-specific context
context = CustomerContext(
    customer_id="cust_123",
    name="Ramesh Patil",
    phone="919876543210",
    lead_temperature="warm",
    interested_cars=["Creta", "Ertiga"],
    conversation_state="ACTIVE",
)

result = await Runner.run(
    starting_agent=customer_agent,
    input="Creta ka price kya hai?",
    context=context,
    session=SQLiteSession(f"customer_{context.customer_id}"),
)
```

### Dynamic Instructions from Context

```python
def dynamic_instructions(ctx: RunContextWrapper[CustomerContext], agent: Agent) -> str:
    c = ctx.context
    return f"""You are a car sales agent at Sharma Motors.
    Customer: {c.name}
    Lead temperature: {c.lead_temperature}
    Interested in: {', '.join(c.interested_cars)}
    Be warm and helpful. Use Hinglish. Keep responses short (2-4 sentences)."""

customer_agent = Agent[CustomerContext](
    name="Sales Agent",
    instructions=dynamic_instructions,
    tools=[search_catalogue, request_escalation],
)
```

### Context Personalization Cookbook Pattern (Memory Notes)

The OpenAI cookbook demonstrates a pattern with global memory (long-term preferences) and session memory (current session notes) -- directly applicable to the daily wrap system:

```python
@dataclass
class TravelState:
    profile: Dict[str, Any]           # CRM data
    global_memory: Dict[str, Any]     # Long-term notes
    session_memory: Dict[str, Any]    # Current session notes
    trip_history: Dict[str, Any]      # Past interactions

@function_tool
def save_memory_note(
    ctx: RunContextWrapper[TravelState],
    text: str,
    keywords: List[str],
) -> dict:
    """Save a memory note about this customer."""
    ctx.context.session_memory["notes"].append({
        "text": text.strip(),
        "last_update_date": _today_iso_utc(),
        "keywords": keywords,
    })
    return {"ok": True}
```

---

## 6. Tool-Calling with Different Tool Sets Per Agent

Each Agent has its own `tools` list:

```python
from agents import Agent, function_tool

# Customer Agent tools
@function_tool
def search_catalogue(query: str) -> str: ...

@function_tool
def get_item_details(item_id: str) -> str: ...

@function_tool
def compare_items(item_a: str, item_b: str) -> str: ...

@function_tool
def request_escalation(reason: str) -> str: ...

customer_agent = Agent(
    name="Customer Agent",
    tools=[search_catalogue, get_item_details, compare_items, request_escalation],
)

# Owner Agent tools (completely different set)
@function_tool
def add_item(name: str, price: float, specs: str) -> str: ...

@function_tool
def update_item(item_id: str, field: str, value: str) -> str: ...

@function_tool
def mark_sold(item_id: str) -> str: ...

@function_tool
def get_active_leads() -> str: ...

@function_tool
def get_stats(query: str) -> str: ...

@function_tool
def open_session(customer_query: str) -> str: ...

@function_tool
def broadcast_message(message: str) -> str: ...

owner_agent = Agent(
    name="Owner Agent",
    tools=[add_item, update_item, mark_sold, get_active_leads, get_stats,
           open_session, broadcast_message, search_catalogue],
)
```

### Conditional Tool Enabling (Runtime)

```python
def session_tools_enabled(ctx: RunContextWrapper[OwnerContext], agent: AgentBase) -> bool:
    return ctx.context.has_active_relay_session

relay_tools = [
    some_relay_tool.as_tool(is_enabled=session_tools_enabled),
]
```

---

## 7. Human-in-the-Loop / Guardrails

### Input/Output Guardrails

Guardrails run validation checks in parallel with agent execution and can trip a "tripwire" to block the response:

```python
from agents import (
    Agent, Runner, GuardrailFunctionOutput,
    InputGuardrailTripwireTriggered, input_guardrail,
    RunContextWrapper, TResponseInputItem,
)
from pydantic import BaseModel

class HomeworkCheck(BaseModel):
    is_math_homework: bool
    reasoning: str

guardrail_agent = Agent(
    name="Homework check",
    instructions="Detect if user is asking for math homework help.",
    output_type=HomeworkCheck,
)

@input_guardrail
async def math_guardrail(
    ctx: RunContextWrapper[None],
    agent: Agent,
    input: str | list[TResponseInputItem],
) -> GuardrailFunctionOutput:
    result = await Runner.run(guardrail_agent, input, context=ctx.context)
    return GuardrailFunctionOutput(
        output_info=result.final_output,
        tripwire_triggered=result.final_output.is_math_homework,
    )

agent = Agent(
    name="Support agent",
    input_guardrails=[math_guardrail],
)

try:
    await Runner.run(agent, "Solve 2x + 3 = 11")
except InputGuardrailTripwireTriggered:
    print("Blocked by guardrail")
```

### Human-in-the-Loop Tool Approval

Tools can be marked with `needs_approval=True` to pause execution and require human approval:

```python
@function_tool(needs_approval=True)
async def cancel_order(order_id: int) -> str:
    return f"Cancelled order {order_id}"

agent = Agent(name="Support agent", tools=[cancel_order])

result = await Runner.run(agent, "Cancel order 123.")

if result.interruptions:
    state = result.to_state()
    for interruption in result.interruptions:
        state.approve(interruption)   # or state.reject(interruption)
    result = await Runner.run(agent, state)

print(result.final_output)
```

### State Serialization for Async Approval

The `RunState` can be serialized to JSON for later resumption (store in DB, wait for human response via WhatsApp, then resume):

```python
result = await Runner.run(agent, "Delete all records")
if result.interruptions:
    state = result.to_state()
    state_json = state.to_json()  # Dict, JSON-serializable
    await db.save_pending_approval(state_json, owner_id)

# Later, when owner approves via WhatsApp:
state_json = await db.load_pending_approval(approval_id)
state = await RunState.from_json(agent, state_json)
state.approve(state.get_interruptions()[0])
result = await Runner.run(agent, state)
```

---

## 8. The "Batch Follow-Up" Pattern

No built-in batch API. The pattern is `asyncio.gather()` over multiple `Runner.run()` calls:

```python
import asyncio
from agents import Agent, Runner

followup_agent = Agent(
    name="Follow-up Agent",
    instructions="Generate a personalized follow-up message for this customer.",
)

async def generate_followup(customer: dict) -> dict:
    session = SQLiteSession(f"customer_{customer['id']}", "conversations.db")
    history = await session.get_items()
    
    prompt = f"""Generate a follow-up message for this customer.
    Name: {customer['name']}
    Interested in: {customer['interested_car']}
    Last contact: {customer['last_contact']}
    Lead temperature: {customer['temperature']}
    """
    
    result = await Runner.run(followup_agent, prompt, context=CustomerContext(**customer))
    return {"customer_id": customer["id"], "message": result.final_output}

async def batch_followup(customers: list[dict]) -> list[dict]:
    results = await asyncio.gather(*(generate_followup(c) for c in customers))
    return results
```

---

## Sources

- [OpenAI Agents SDK - Official Documentation](https://openai.github.io/openai-agents-python/)
- [OpenAI Agents SDK - GitHub Repository](https://github.com/openai/openai-agents-python)
- [Handoffs - OpenAI Agents SDK](https://openai.github.io/openai-agents-python/handoffs/)
- [Sessions - OpenAI Agents SDK](https://openai.github.io/openai-agents-python/sessions/)
- [Running Agents - OpenAI Agents SDK](https://openai.github.io/openai-agents-python/running_agents/)
- [Context Management - OpenAI Agents SDK](https://openai.github.io/openai-agents-python/context/)
- [Tools - OpenAI Agents SDK](https://openai.github.io/openai-agents-python/tools/)
- [Guardrails - OpenAI Agents SDK](https://openai.github.io/openai-agents-python/guardrails/)
- [Agent Orchestration - OpenAI Agents SDK](https://openai.github.io/openai-agents-python/multi_agent/)
- [Orchestration and Handoffs Guide - OpenAI API](https://developers.openai.com/api/docs/guides/agents/orchestration)
- [Guardrails and Human Review - OpenAI API](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals)
- [Parallel Agents Cookbook - OpenAI](https://developers.openai.com/cookbook/examples/agents_sdk/parallel_agents)
- [Context Personalization Cookbook - OpenAI](https://developers.openai.com/cookbook/examples/agents_sdk/context_personalization)
- [Session Memory Cookbook - OpenAI](https://developers.openai.com/cookbook/examples/agents_sdk/session_memory)
- [Use Codex with the Agents SDK - OpenAI](https://developers.openai.com/codex/guides/agents-sdk)
- [OpenAI Customer Service Agents Demo - GitHub](https://github.com/openai/openai-cs-agents-demo)
- [Telegram OpenAI AgentKit - GitHub](https://github.com/hschickdevs/telegram-openai-agentkit)
- [Multi-Agent Portfolio Collaboration Cookbook - OpenAI](https://developers.openai.com/cookbook/examples/agents_sdk/multi-agent-portfolio-collaboration/multi_agent_portfolio_collaboration)
- [Handoff Filters Reference - OpenAI Agents SDK](https://openai.github.io/openai-agents-python/ref/extensions/handoff_filters/)
