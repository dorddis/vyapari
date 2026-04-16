"""Context dataclasses for OpenAI Agents SDK RunContextWrapper + response types.

Context classes are passed to Runner.run() and are accessible in all tools
via wrapper.context. They are NOT sent to the LLM — purely local state.

AgentResponse is returned from run_customer_agent / run_owner_agent
so the caller can send images, escalation notifications, etc.
"""

from dataclasses import dataclass, field


@dataclass
class CustomerContext:
    """Per-customer context injected into the Customer Agent."""
    customer_id: str  # wa_id
    name: str = "Customer"
    phone: str = ""
    lead_status: str = "new"
    interested_cars: list[str] = field(default_factory=list)
    conversation_state: str = "active"
    conversation_id: str = ""
    source: str | None = None  # which reel/link they came from
    business_id: str = "demo-sharma-motors"


@dataclass
class StaffContext:
    """Per-staff context injected into the Owner/SDR Agent."""
    staff_id: str  # wa_id
    name: str = "Staff"
    role: str = "owner"  # "owner" or "sdr"
    business_id: str = "demo-sharma-motors"
    has_active_relay: bool = False
    active_relay_customer: str | None = None  # customer wa_id if in relay


@dataclass
class AgentResponse:
    """Rich response from run_customer_agent / run_owner_agent.

    The caller (router/web_api) uses this to send additional messages
    beyond the text reply — images, escalation notifications, etc.
    """
    text: str
    images: list[str] = field(default_factory=list)  # image URLs to send
    is_escalation: bool = False
    escalation_reason: str = ""
    escalation_summary: str = ""  # for owner notification
    notify_customers: list[dict] = field(default_factory=list)  # [{"wa_id": ..., "message": ...}]
