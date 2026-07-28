from src.graphs.chat_graph import stream_agent
from src.config.settings import (
    LLM_PROVIDER,
    LLM_MODEL
)
from pathlib import Path


workspace = str(Path.cwd())
provider = LLM_PROVIDER
model = LLM_MODEL
print(f"Workspace: {workspace}")
thread_id = "terminal-session"


while True:
    user_message = input("\nYou: ")

    # Ignore empty input
    if not user_message.strip():
        continue

    # Exit PulseCodeAI
    if user_message.lower() in ["exit", "quit"]:
        print("\nPulseCodeAI: Goodbye!")
        break
        
    if user_message.strip() == "/model":
        print(f"\nCurrent model: {provider} / {model}")
        continue
    # Change model/provider at runtime
    if user_message.startswith("/model "):
        parts = user_message.split(maxsplit=2)

        if len(parts) != 3:
            print("\nUsage: /model <provider> <model>")
            continue

        provider = parts[1]
        model = parts[2]

        print(f"\nSwitched to {provider} / {model}")
        continue

    # Send normal user messages to the agent
    try:
        response = stream_agent(
            user_message,
            thread_id=thread_id,
            provider=provider,
            model=model,
            workspace=workspace
        )

        print(f"\nPulseCodeAI: {response}")

    except Exception as error:
        print(f"\nPulseCodeAI Error: {error}")