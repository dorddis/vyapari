export const COLORS = {
  green: "#2b7a4b",
  red: "#b34e35",
  orange: "#d86f31",
  gold: "#b07b17",
  amber: "#c78d45",
  yellow: "#e5c07b",
  greenDark: "#1f6d43",
};

export const conversationSeeds = [
  {
    id: "lead-aman",
    name: "Aman",
    source: "Creta reel",
    phone: "+91 00000 00001",
    status: "hot",
    needsAttention: true,
    waitingSince: "2m ago",
    vehicleInterest: ["2022 Tata Nexon XZ+", "2021 Maruti Brezza VXi"],
    budget: "Around 8 lakh",
    intent: "Family SUV, financing-sensitive, ready for visit if EMI works",
    objection: "Sticker price feels high",
    recommendation: "Owner should confirm EMI structure and push for showroom visit tomorrow.",
    agentMode: "human",
    summary:
      "Customer came from the Creta reel but shifted to Nexon vs Brezza. Good fit for a finance-assisted close.",
    messages: [
      {
        id: "m1",
        role: "system",
        channel: "whatsapp",
        text: "Lead entered from Creta reel deep link.",
        timestamp: "09:42",
      },
      {
        id: "m2",
        role: "customer",
        channel: "whatsapp",
        text: "Koi SUV chahiye family ke liye. Budget around 8 lakh hai.",
        timestamp: "09:43",
      },
      {
        id: "m3",
        role: "agent",
        channel: "whatsapp",
        text: "Nexon safety ke liye strong hai, Brezza resale aur mileage ke liye. Family size kitni hai?",
        timestamp: "09:43",
      },
      {
        id: "m4",
        role: "customer",
        channel: "whatsapp",
        text: "Family ke liye hi hai, budget stretch mushkil hai. Rajesh se baat ho sakti hai?",
        timestamp: "09:45",
      },
      {
        id: "m5",
        role: "system",
        channel: "dashboard",
        text: "Escalation raised: negotiation + qualified buyer.",
        timestamp: "09:45",
      },
      {
        id: "m6",
        role: "owner",
        channel: "dashboard",
        text: "Haan bhai, down payment aur EMI structure ke saath kaam ho jayega. Kal dekhne aa jao.",
        timestamp: "09:47",
      },
    ],
  },
  {
    id: "lead-ramesh",
    name: "Ramesh",
    source: "Direct WhatsApp",
    phone: "+91 00000 00002",
    status: "warm",
    needsAttention: false,
    waitingSince: "active now",
    vehicleInterest: ["2021 Hyundai Creta SX"],
    budget: "9 to 10 lakh",
    intent: "Availability check and token follow-up",
    objection: "Wants reservation confidence before visiting",
    recommendation: "Keep agent active and reassure on hold/reservation status.",
    agentMode: "agent",
    summary:
      "Strong buyer signal. Already sent token screenshot for the Nexon and may ask for pickup details next.",
    messages: [
      {
        id: "m7",
        role: "customer",
        channel: "whatsapp",
        text: "Nexon available hai?",
        timestamp: "10:02",
      },
      {
        id: "m8",
        role: "agent",
        channel: "whatsapp",
        text: "Nexon XZ+ abhi hold pe hai, but Brezza VXi 8.95L pe available hai. Interested?",
        timestamp: "10:03",
      },
      {
        id: "m9",
        role: "customer",
        channel: "whatsapp",
        text: "Agar token bheju toh reserve ho jayegi?",
        timestamp: "10:04",
      },
    ],
  },
  {
    id: "lead-neha",
    name: "Neha",
    source: "Fortuner reel",
    phone: "+91 00000 00003",
    status: "new",
    needsAttention: false,
    waitingSince: "6m ago",
    vehicleInterest: ["2022 Tata Punch", "WagonR"],
    budget: "Under 6 lakh",
    intent: "Exploring compact family options",
    objection: "Does not like older inventory",
    recommendation: "Use finance recovery and newer Punch upsell.",
    agentMode: "agent",
    summary:
      "Early-stage lead. Good candidate for AI-driven recommendation and EMI-led upsell.",
    messages: [
      {
        id: "m10",
        role: "customer",
        channel: "whatsapp",
        text: "Show me cars under 5 lakh",
        timestamp: "11:11",
      },
      {
        id: "m11",
        role: "agent",
        channel: "whatsapp",
        text: "Humare paas Alto K10, WagonR aur ek Punch option hai. Family use ke liye dekh rahe ho?",
        timestamp: "11:12",
      },
    ],
  },
];

export const inventorySeeds = [
  {
    id: "car-1",
    name: "2022 Tata Nexon XZ+",
    status: "reserved",
    price: "8.75L",
    inquiries: 6,
    source: "Top reel performer",
  },
  {
    id: "car-2",
    name: "2021 Maruti Brezza VXi",
    status: "available",
    price: "8.95L",
    inquiries: 4,
    source: "High comparison traffic",
  },
  {
    id: "car-3",
    name: "2021 Hyundai Creta SX",
    status: "available",
    price: "9.75L",
    inquiries: 2,
    source: "Reel anchor listing",
  },
  {
    id: "car-4",
    name: "2022 Tata Punch Adventure",
    status: "available",
    price: "6.15L",
    inquiries: 3,
    source: "Budget recovery pick",
  },
  {
    id: "car-5",
    name: "2021 Hyundai Creta SX Phantom Black",
    status: "sold",
    price: "9.4L",
    inquiries: 5,
    source: "Recently closed by owner",
  },
];

// Values reflect the 3 seed conversations; update when more are added.
export const insightCards = [
  {
    label: "Leads Today",
    value: "3",
    note: "+1 from yesterday",
  },
  {
    label: "Hot Leads",
    value: "1",
    note: "1 needs owner follow-up",
  },
  {
    label: "Top Price Band",
    value: "6L-9L",
    note: "SUV demand strongest",
  },
  {
    label: "FAQ Gap",
    value: "8 asks",
    note: "Home delivery this week",
  },
];

export const ownerAgentSeed = [
  {
    id: "oa-1",
    role: "agent",
    text: "Good morning. You have 3 hot leads, 2 escalations waiting, and Nexon is still your most asked-about car.",
  },
];

export const priceBandDemand = [
  {
    label: "Under 5L",
    value: 4,
    display: "4",
    color: COLORS.orange,
  },
  {
    label: "6L-9L",
    value: 5,
    display: "5",
    color: COLORS.green,
  },
  {
    label: "9L+",
    value: 3,
    display: "3",
    color: COLORS.red,
  },
];

export const weeklyLeadTrend = [
  { label: "Mon", value: 5, display: "5", color: COLORS.amber },
  { label: "Tue", value: 7, display: "7", color: COLORS.orange },
  { label: "Wed", value: 6, display: "6", color: COLORS.gold },
  { label: "Thu", value: 9, display: "9", color: COLORS.green },
  { label: "Fri", value: 12, display: "12", color: COLORS.greenDark },
  { label: "Sat", value: 11, display: "11", color: COLORS.green },
];

export const sourceBreakdown = [
  {
    label: "Creta reel",
    value: 6,
    display: "6 leads",
    hint: "Most qualified source",
    color: COLORS.green,
  },
  {
    label: "Direct WhatsApp",
    value: 4,
    display: "4 leads",
    hint: "Strong intent traffic",
    color: COLORS.orange,
  },
  {
    label: "Fortuner reel",
    value: 2,
    display: "2 leads",
    hint: "Higher browsing intent",
    color: COLORS.gold,
  },
];

export const aiRecommendations = [
  {
    title: "Jump into Aman now",
    text: "Strong close potential. Finance concern is the last blocker and the customer already asked for Rajesh by name.",
  },
  {
    title: "Push 6L-9L SUVs in the next reel",
    text: "Current demand is clustered in the mid-range family SUV segment.",
  },
  {
    title: "Add a delivery FAQ",
    text: "Customers asked about delivery and location repeatedly this week.",
  },
];

export const topComparisonCars = "Nexon, Brezza";

export const leadStageData = [
  {
    label: "New inquiries",
    value: 100,
    display: "12",
    note: "Top of funnel today",
    color: COLORS.yellow,
  },
  {
    label: "Qualified",
    value: 66,
    display: "8",
    note: "Matches found and needs clear",
    color: COLORS.orange,
  },
  {
    label: "Escalated",
    value: 33,
    display: "4",
    note: "Owner or SDR should step in",
    color: COLORS.red,
  },
  {
    label: "Visits booked",
    value: 16,
    display: "2",
    note: "Strong buying signal",
    color: COLORS.green,
  },
];
