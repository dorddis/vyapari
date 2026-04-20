# Dashboard Frontend

React dashboard scaffold for the Vyapari owner experience.

## What this includes

- Lead inbox with WhatsApp-to-dashboard conversation continuity
- Owner takeover reply box and agent resume control
- AI copilot panel for summaries and natural-language owner queries
- Inventory snapshot view
- Insights view with recommended next actions

## Run locally

```bash
cd src/dashboard_frontend
npm install
npm run dev
```

## Notes

- Current data is mocked in `src/data.js`
- This is intended to become the owner-facing web dashboard
- The next integration step is wiring these views to FastAPI APIs and live conversation state
