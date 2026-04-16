"""Quick local test - chat with the bot in terminal. No WhatsApp needed."""

from conversation import get_reply

CUSTOMER_ID = "test-user-001"

print("=" * 50)
print("Sharma Motors AI Sales Agent (local test)")
print("Type 'quit' to exit")
print("=" * 50)
print()

while True:
    msg = input("You: ").strip()
    if msg.lower() in ("quit", "exit", "q"):
        break
    if not msg:
        continue

    reply = get_reply(customer_id=CUSTOMER_ID, message=msg)
    print(f"\nBot: {reply}\n")
