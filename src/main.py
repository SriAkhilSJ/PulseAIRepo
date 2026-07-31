from pathlib import Path

from src.config.settings import (
    LLM_MODEL,
    LLM_PROVIDER,
)
from src.context.token_tracker import TokenTracker
from src.graphs.chat_graph import get_agent_status, stream_agent


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


    # Show repo map
    if user_message.strip() == "/map":
        from src.context.repo_map import get_repo_map

        try:
            map_text = get_repo_map(workspace, max_tokens=2000)
            print(f"\n{map_text}")
        except Exception as error:
            print(f"\nCould not build repo map: {error}")

        continue

    # Show token usage
    if user_message.strip() == "/cost":
        status = get_agent_status(thread_id)
        cost = status.get("cost", {})

        if cost.get("calls_made", 0) > 0:
            print(f"\n{TokenTracker.format_usage(cost)}")
        else:
            print("\nNo token usage recorded yet.")

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
            workspace=workspace,
        )

        print(f"\nPulseCodeAI: {response}")

        # Show token usage for this turn
        status = get_agent_status(thread_id)
        cost = status.get("cost", {})

        if cost.get("calls_made", 0) > 0:
            print(f"\n[Usage] {TokenTracker.format_usage(cost)}")

    except Exception as error:
        print(f"\nPulseCodeAI Error: {error}")
