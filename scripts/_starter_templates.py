"""Definitions of the starter Meta templates the dispatcher expects.

Kept in a standalone module (not inside scripts/register_starter_templates.py)
so tests can import it without running a CLI.

Template JSON follows the WhatsApp Cloud API template creation schema:
  https://developers.facebook.com/docs/whatsapp/business-management-api/message-templates

Parameter positions ({{1}}, {{2}}) are filled at send-time by the
dispatcher's `variables` list.
"""

from __future__ import annotations


# -------------------------------------------------------------------------
# followup_24h  (UTILITY)
# After a customer has gone quiet within the 24h window, we've already
# sent our agent's free-form replies. This template is for ~the next day
# ("did you still want a visit?"). English and Hinglish/Hindi variants.
# -------------------------------------------------------------------------

FOLLOWUP_24H_EN = {
    "name": "followup_24h",
    "language": "en",
    "category": "UTILITY",
    "components": [
        {
            "type": "BODY",
            "text": (
                "Hi {{1}}, just checking in on the {{2}} you were looking "
                "at. Want me to share more photos or schedule a visit? "
                "Happy to help whenever works for you."
            ),
            "example": {"body_text": [["Rahul", "Maruti Swift"]]},
        },
        {"type": "FOOTER", "text": "Reply STOP to opt out."},
    ],
}


FOLLOWUP_24H_HI = {
    "name": "followup_24h",
    "language": "hi",
    "category": "UTILITY",
    "components": [
        {
            "type": "BODY",
            "text": (
                "Namaste {{1}}, aapne {{2}} dekha tha — aur photos ya visit "
                "plan karna hai? Jab bhi ho, bata dijiye."
            ),
            "example": {"body_text": [["Rahul", "Maruti Swift"]]},
        },
        {"type": "FOOTER", "text": "Reply STOP to opt out."},
    ],
}


# -------------------------------------------------------------------------
# reengagement_7d  (MARKETING)
# Used for "new stock dropped" re-engagement after the 24h session and
# followup have both elapsed. Marketing category has stricter Meta review.
# -------------------------------------------------------------------------

REENGAGEMENT_7D_EN = {
    "name": "reengagement_7d",
    "language": "en",
    "category": "MARKETING",
    "components": [
        {
            "type": "BODY",
            "text": (
                "Hi {{1}}, we just got a few new arrivals that match what "
                "you were looking for. {{2}} might be a good fit — want "
                "the details?"
            ),
            "example": {"body_text": [["Rahul", "2023 Hyundai Creta"]]},
        },
        {"type": "FOOTER", "text": "Reply STOP to opt out."},
    ],
}


# -------------------------------------------------------------------------
# otp_owner_login  (AUTHENTICATION)
# One-time code for staff login. Authentication templates have a special
# Meta schema — no positional body params; Meta inserts the OTP code
# directly and auto-renders the body text per locale.
# -------------------------------------------------------------------------

OTP_OWNER_LOGIN_EN = {
    "name": "otp_owner_login",
    "language": "en",
    "category": "AUTHENTICATION",
    "components": [
        {
            "type": "BODY",
            "add_security_recommendation": True,
        },
        {
            "type": "FOOTER",
            "code_expiration_minutes": 10,
        },
        {
            "type": "BUTTONS",
            "buttons": [
                {"type": "OTP", "otp_type": "COPY_CODE", "text": "Copy code"}
            ],
        },
    ],
}


# -------------------------------------------------------------------------
# Registry — iterated by scripts/register_starter_templates.py
# -------------------------------------------------------------------------

STARTER_TEMPLATES = [
    FOLLOWUP_24H_EN,
    FOLLOWUP_24H_HI,
    REENGAGEMENT_7D_EN,
    OTP_OWNER_LOGIN_EN,
]
