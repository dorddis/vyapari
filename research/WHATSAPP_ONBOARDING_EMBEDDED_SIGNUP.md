# WhatsApp Business Onboarding: Embedded Signup & Platform Architecture

**Date:** April 16, 2026
**Context:** Codex Hackathon -- how does a dealer (SMB) connect their WhatsApp number to our platform without touching API keys?

---

## Core Concept

It's **one Meta App (ours)** that gets authorized by multiple businesses. Not "two APIs."

```
YOUR PLATFORM (one Meta Developer App)
     |
     |-- Embedded Signup button on your website
     |
     v
DEALER CLICKS "Connect WhatsApp"
     |
     |-- Facebook login popup (Meta-hosted)
     |-- Creates/selects their own WABA
     |-- Verifies their phone number (OTP)
     |-- Grants YOUR app permission
     |
     v
YOUR APP NOW HAS API ACCESS TO THEIR NUMBER
     |-- Send/receive messages on their behalf
     |-- They keep using WhatsApp Business App (coexistence)
```

The dealer never touches API keys, webhooks, or developer portals. They click a button, log in with Facebook, verify their number, done.

---

## 1. Meta's Embedded Signup Flow

### What the Business Owner Sees (Step by Step)

The Embedded Signup flow is a Meta-hosted UI that launches as a popup/overlay from your platform's website:

1. **Facebook/Meta Login** -- Authenticate with their Facebook or Meta Business credentials
2. **Terms of Service** -- Accept your platform's terms of service
3. **Permission Grants** -- Select WhatsApp APIs and grant your app permissions (`whatsapp_business_management` and `whatsapp_business_messaging`)
4. **Business Portfolio** -- Choose an existing Meta Business Portfolio or create a new one
5. **WABA Creation** -- Choose or create a WhatsApp Business Account (WABA)
6. **Phone Number** -- Register and verify a business phone number (OTP via SMS or voice call)
7. **Display Name** -- Set a display name for their WhatsApp presence
8. **Confirmation** -- Review and finish

Total time: ~10-15 minutes. Desktop- and mobile-compatible. Auto-adapts to 30 languages.

### Technical Flow (Frontend)

```javascript
// 1. Load Facebook JavaScript SDK
window.fbAsyncInit = function() {
  FB.init({
    appId: 'YOUR_APP_ID',
    autoLogAppEvents: true,
    xfbml: true,
    version: 'v23.0'
  });
};

// 2. Launch Embedded Signup when user clicks your "Connect WhatsApp" button
function launchWhatsAppSignup() {
  FB.login(function(response) {
    if (response.authResponse) {
      const code = response.authResponse.code;
      // Send this code to your backend -- it expires in 30 seconds!
    }
  }, {
    config_id: 'YOUR_CONFIG_ID',     // from Meta App Dashboard
    response_type: 'code',
    override_default_response_type: true,
    extras: {
      setup: {
        solutionID: 'YOUR_SOLUTION_ID'
      }
    }
  });
}

// 3. Listen for session info (WABA ID, phone number ID)
window.addEventListener('message', (event) => {
  if (event.data.type === 'WA_EMBEDDED_SIGNUP') {
    const { data } = event.data;
    // data contains: waba_id, phone_number_id
    // Send to your backend
  }
});
```

### Technical Flow (Backend)

```python
# 4. Exchange the code for a customer-scoped business token (MUST happen within 30 seconds)
# GET https://graph.facebook.com/v23.0/oauth/access_token?
#     client_id=<APP_ID>
#     &client_secret=<APP_SECRET>
#     &code=<CODE_FROM_FRONTEND>

# 5. Register the phone number for Cloud API
# POST https://graph.facebook.com/v23.0/<PHONE_NUMBER_ID>/register

# 6. Subscribe your app to webhooks on the customer's WABA
# POST https://graph.facebook.com/v23.0/<WABA_ID>/subscribed_apps

# 7. Now you can send messages on behalf of the business
# POST https://graph.facebook.com/v23.0/<PHONE_NUMBER_ID>/messages
```

### Prerequisites for Your Platform

- A Meta Developer App (created at developers.facebook.com)
- App Review approval for `whatsapp_business_management` and `whatsapp_business_messaging` permissions (required for production; development mode lets you test with admin/developer/tester roles)
- A `config_id` generated via the Embedded Signup Integration Helper in the App Dashboard
- HTTPS-enabled domain added to both Allowed Domains and Valid OAuth Redirect URIs
- Webhook endpoint to receive incoming messages

### Rate Limits

- Default: 10 customer onboardings per 7 days
- After App Review approval: increases to 200

---

## 2. BSP / Tech Provider Requirements

### The Three Tiers

| Tier | What It Is | Requirements | Embedded Signup |
|------|-----------|--------------|----------------|
| **Direct Developer** | Any developer using Cloud API for their own business | Meta Developer account, create an app | No (for onboarding others) |
| **Tech Provider** | ISV building solutions for other businesses | Enroll in Meta's Tech Provider Program | YES |
| **Solution Partner** | Full BSP with Meta Business Partner status | Meta Business Partner certification | YES + credit lines |

### What's Needed When

- **Hackathon:** Direct Developer. No partner enrollment needed. Test number + up to 5 recipients.
- **Production (onboarding other businesses):** Must enroll as Tech Provider. Meta requires all ISVs to enroll. Process takes 3-4 weeks.
- **Scaling:** After onboarding 10+ business clients, can upgrade to Tech Partner.

**Key difference:** Tech Providers cannot extend credit lines. Business customers must provide their own payment method to Meta. Solution Partners can invoice customers directly.

---

## 3. Using the Dealer's Existing WhatsApp Business App Number

### Coexistence Mode

Meta's "WhatsApp Business App Coexistence" allows a business to use BOTH the WhatsApp Business App AND the Cloud API on the same number simultaneously.

**During Embedded Signup:**
1. Configure `featureType: "whatsapp_business_app_onboarding"` in Embedded Signup v3+ configuration
2. Business owner enters their existing WhatsApp Business App phone number
3. They receive a verification message from Facebook's official account in the Business App
4. A QR code appears on screen -- they scan it from within the Business App
5. They choose whether to share chat history (up to 6 months of 1:1 chats, 2 weeks of media)
6. Connection completes in ~2 minutes

**After connection:**
- Owner keeps using their WhatsApp Business App for 1:1 conversations
- Your platform sends API messages (automated replies, chatbot) via Cloud API
- Messages sync both ways (via `smb_message_echoes` webhook)
- Contacts sync automatically
- Up to 4 linked devices remain supported

**Limitations:**
- Throughput capped at 20 messages per second
- Group chats NOT supported via Cloud API
- Disappearing messages and broadcast lists disabled
- Blue badge verification does NOT transfer
- All companion devices unlinked during onboarding (can re-link after, except Windows and WearOS)

---

## 4. The "Shared Number" Alternative

Instead of connecting to the dealer's number, the platform provides its own WhatsApp Business number.

**WhatsApp's policy:** Each WABA must have its own unique phone number. One number = one business identity. You cannot route a single number to multiple independent businesses.

**What platforms actually do:** They require each business to connect their OWN number via Embedded Signup. The "shared" aspect is team collaboration on that number, not sharing across businesses.

**For hackathon:** Use a single test number you control. Nobody expects production onboarding at a hackathon.

---

## 5. How WATI, AiSensy, Interakt, Gallabox Do Onboarding

All use Meta's Embedded Signup under the hood. Common pattern:

1. Business signs up on platform website
2. Platform shows "Connect WhatsApp" button
3. Button triggers Meta's Embedded Signup popup
4. Business authenticates via Facebook
5. Creates/selects WABA
6. Verifies phone number (OTP)
7. Platform exchanges token, registers number, subscribes to webhooks (automatic)
8. Business is live

**WATI Coexistence flow specifically:**
1. Select "Connect your WhatsApp Business app (WhatsApp Coexistence)"
2. Facebook login
3. Select existing Business Portfolio
4. Enter active phone number (currently in WhatsApp Business App)
5. QR code appears -- Facebook sends message to Business App
6. Open message in Business App, click "Connect"
7. Scan QR code
8. Choose to import past chats
9. Connected in ~2 minutes

---

## 6. On-Behalf-Of (OBO) Model -- DEPRECATED

The OBO WABA ownership model has been deprecated. Previously a BSP would create a WABA "on behalf of" a business. Now the business always owns their own WABA. Your app gets authorized access via Embedded Signup permissions. If they leave your platform, they keep their number, WABA, and templates.

---

## 7. Hackathon Setup (Fastest Path)

### Option A: Direct Cloud API with Test Number (RECOMMENDED -- 20 minutes)

| Step | Action | Time |
|------|--------|------|
| 1 | Create Meta Developer App at developers.facebook.com | 5 min |
| 2 | Select "Connect with customers through WhatsApp" use case | 1 min |
| 3 | Get auto-generated test phone number + temp access token | 2 min |
| 4 | Add your phones as test recipients (up to 5) | 2 min |
| 5 | Set up ngrok + PyWa webhook | 10 min |

**Limitations of test number:**
- Only 5 pre-verified recipient numbers
- Template messages only for first outreach; free-form after user replies
- Token expires ~24 hours (create System User token for permanent)

### Option B: Register Your Own Number (30 minutes)

1. Complete Option A
2. In App Dashboard > API Setup > "Add phone number"
3. Enter a real phone number (must NOT be registered on WhatsApp -- delete account first)
4. Verify via SMS/voice call OTP
5. Now you have a real number that can receive inbound messages + webhooks

### Option C: Mock Onboarding UI (Best for Demo Presentation)

1. Set up Option A or B for actual messaging
2. Build a simple frontend that SIMULATES Embedded Signup screens
3. "Connect WhatsApp" button -> mock Facebook login -> mock WABA creation -> mock verification
4. At the end, connect to your actual Cloud API backend
5. Demonstrates the production vision without needing Tech Provider enrollment

---

## 8. Phone Number Registration Details

### During Embedded Signup

1. Business enters phone number
2. Chooses SMS or voice call verification, enters OTP
3. Your backend calls `POST /v23.0/<PHONE_NUMBER_ID>/register`
4. Number reaches "CONNECTED" status
5. System generates new WABA, associates with business's Meta Business Portfolio, grants your app access

### Migration Paths

**Full Migration (number moves to API only):**
- Number deregistered from WhatsApp Business App
- Becomes Cloud API-only
- All companion devices unlinked
- Old chat history on phone NOT accessible via API

**Coexistence (recommended):**
- Number stays on Business App AND connects to Cloud API
- Both channels work simultaneously
- Up to 6 months chat history imported
- Business keeps using app for 1:1; API handles automation

### Can It Be Migrated Back?

Yes -- deregister from Cloud API, re-register on Business App. Some disruption expected. Message history from API period may not transfer back.

---

## Impact on Design Doc

**Hackathon:** Agent uses a test number. Owner onboards via `/setup` in the chat (already designed in DESIGN_DOC.md). No changes needed.

**Production:** Add an Embedded Signup button on a web portal. Dealer connects their own number. Coexistence mode enabled. Agent gets API access automatically. Core architecture (agent, relay, tools, sessions) stays identical.

---

## Sources

- [Embedded Signup Overview -- Meta for Developers](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/overview/)
- [Embedded Signup Implementation -- Meta for Developers](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation/)
- [Onboarding Business App Users (Coexistence) -- Meta for Developers](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users/)
- [WhatsApp Cloud API Get Started -- Meta for Developers](https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started)
- [Solution Provider Overview -- Meta for Developers](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/overview)
- [Business Phone Numbers -- Meta for Developers](https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/phone-numbers)
- [Tech Provider Program -- Twilio](https://www.twilio.com/docs/whatsapp/isv/tech-provider-program)
- [WATI Embedded Signup Help](https://support.wati.io/en/articles/11462961-how-to-connect-your-whatsapp-number-to-wati-via-embedded-signup-mm-lite-api)
- [WATI Coexistence Onboarding](https://support.wati.io/en/articles/11822421-onboarding-to-whatsapp-coexistence-coex-via-wati)
- [AiSensy WhatsApp API Application](https://wiki.aisensy.com/en/articles/11477927-how-to-apply-for-whatsapp-business-api)
- [Interakt Getting Started](https://www.interakt.shop/blog/how-to-get-started-with-whatsapp-business-api-on-interakt/)
- [Gallabox Connect WhatsApp](https://docs.gallabox.com/connect-whatsapp-channel/connect-your-whatsapp)
- [GitHub: WhatsApp Embedded Signup Example](https://github.com/Gaurang200/whatsapp-embedded-signup)
- [WhatsApp BSP Guide -- Respond.io](https://respond.io/blog/whatsapp-business-solution-provider)
