"""Business tools — FAQ, business info, greeting."""

import json

from catalogue import BUSINESS, FAQS, get_business_context


def tool_get_business_info() -> str:
    """Get dealership info: hours, address, contact, landmark, nearest metro."""
    return json.dumps({
        "success": True,
        "data": {
            "name": BUSINESS["business_name"],
            "address": get_business_context(),
        },
        "message": "Business info retrieved.",
    })


def tool_get_faq_answer(topic: str) -> str:
    """Find FAQ answers matching a topic keyword."""
    topic_lower = topic.lower()
    matches = []
    for faq in FAQS["faqs"]:
        if (
            topic_lower in faq["question"].lower()
            or topic_lower in faq["answer"].lower()
            or topic_lower in faq.get("category", "").lower()
        ):
            matches.append({"question": faq["question"], "answer": faq["answer"]})

    if not matches:
        return json.dumps({
            "success": True,
            "data": [],
            "message": f"No FAQs found for '{topic}'. Let me check with our team.",
        })

    return json.dumps({
        "success": True,
        "data": matches[:3],
        "message": f"Found {len(matches)} FAQ{'s' if len(matches) != 1 else ''} about '{topic}'.",
    })


def tool_add_faq(question: str, answer: str, category: str = "General") -> str:
    """Add a new FAQ entry."""
    max_id = max((f["id"] for f in FAQS["faqs"]), default=0)
    new_faq = {
        "id": max_id + 1,
        "question": question,
        "answer": answer,
        "category": category,
    }
    FAQS["faqs"].append(new_faq)
    FAQS["total_faqs"] = len(FAQS["faqs"])

    return json.dumps({
        "success": True,
        "data": {"id": new_faq["id"]},
        "message": f"FAQ added: '{question}'",
    })


def tool_update_greeting(new_greeting: str) -> str:
    """Update the business greeting message."""
    old = BUSINESS.get("greeting_message", "")
    BUSINESS["greeting_message"] = new_greeting

    return json.dumps({
        "success": True,
        "data": {"old": old, "new": new_greeting},
        "message": "Greeting updated.",
    })
