import os

# The suite must never send traces anywhere, even though backend/.env may hold real Langfuse keys and
# load_settings() copies .env into the environment. Tests that exercise tracing opt in explicitly.
os.environ["REBUTTAL_TRACING"] = "0"

# Likewise no test may call a real model, even though backend/.env holds provider keys.
os.environ["REBUTTAL_REASONER"] = "rules"

# And no test may build a real-sandbox runtime, whatever REBUTTAL_MOCK says in backend/.env.
os.environ["REBUTTAL_MOCK"] = "1"
