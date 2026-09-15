import os
from pathlib import Path

from src.config.settings import (
    LLM_MODEL,
    LLM_PROVIDER,
)
from src.context.token_tracker import TokenTracker
from src.graphs.chat_graph import get_agent_status, stream_agent, fork_conversation, export_session_analytics


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

    # Exit CrusorCodeAI
    if user_message.lower() in ["exit", "quit"]:
        print("\nCrusorCodeAI: Goodbye!")
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

    # Fork conversation
    if user_message.strip().startswith("/fork"):
        parts = user_message.split(maxsplit=1)
        new_name = parts[1] if len(parts) > 1 else None
        result = fork_conversation(thread_id, new_name)
        if result.startswith("No saved state"):
            print(f"\nCrusorCodeAI: {result}")
        else:
            thread_id = result
            print(f"\nCrusorCodeAI: 🌿 Forked to new session: {thread_id}")
        continue

    # Show persistent memories
    if user_message.strip() == "/memories":
        import json
        home = os.path.expanduser("~")
        mem_path = os.path.join(home, ".crusorai", "memories.json")
        if os.path.exists(mem_path):
            try:
                with open(mem_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                memories = data.get("memories", [])
                if not memories:
                    print("\nCrusorCodeAI: No memories stored yet.")
                else:
                    print(f"\nCrusorCodeAI: 📚 {len(memories)} memories stored:")
                    for i, mem in enumerate(memories[-5:], 1):
                        task = mem.get("task", "Unknown")[:60]
                        mtype = mem.get("type", "memory")
                        print(f"  {i}. [{mtype}] {task}...")
            except Exception as e:
                print(f"\nCrusorCodeAI: Could not read memories: {e}")
        else:
            print("\nCrusorCodeAI: No memory file found.")
        continue

    # Show learned conventions
    if user_message.strip() == "/conventions":
        from src.context.convention_learner import ConventionLearner
        learner = ConventionLearner()
        conventions = learner.scan_workspace(workspace)
        if not conventions:
            print("\nCrusorCodeAI: No conventions learned yet.")
        else:
            print("\nCrusorCodeAI: 🎨 Learned project conventions:")
            for key, value in conventions.items():
                if isinstance(value, dict):
                    print(f"  {key}:")
                    for k, v in value.items():
                        print(f"    {k}: {v}")
                elif isinstance(value, list):
                    print(f"  {key}: {', '.join(value) if value else 'none'}")
                else:
                    print(f"  {key}: {value}")
        continue

    # Launch web dashboard
    if user_message.strip() == "/web":
        import subprocess
        import sys
        print("\nCrusorCodeAI: 🌐 Starting dashboard server...")
        print("   Open http://localhost:8080 in your browser")
        subprocess.Popen([
            sys.executable, "src/dashboard_server.py"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        continue

    # Show cost routing info
    if user_message.strip() == "/route":
        from src.agents.cost_router import cost_router
        print(f"\nCrusorCodeAI: 🧭 {cost_router.get_last_route_info()}")
        continue

    if user_message.strip().startswith("/route "):
        from src.agents.cost_router import cost_router
        tier = user_message.split(maxsplit=1)[1].strip().lower()
        if tier in ("cheap", "standard", "premium"):
            cost_router.override_tier(tier)
            print(f"\nCrusorCodeAI: Locked routing to {tier.upper()} tier.")
        else:
            print("\nCrusorCodeAI: Usage: /route cheap|standard|premium")
        continue

    # List skills
    if user_message.strip() == "/skills":
        from src.agents.skill_manager import skill_manager
        skills = skill_manager.list_skills()
        if not skills:
            print("\nCrusorCodeAI: No skills defined yet.")
            print("Add one with: /skill add \"Name\" trigger1,trigger2 \"Instruction\"")
        else:
            print(f"\nCrusorCodeAI: 🎯 {len(skills)} skill(s):")
            for s in skills:
                status = "✅" if s.get("enabled", True) else "❌"
                triggers = ", ".join(s["triggers"])
                print(f"  {status} {s['name']} — triggers: [{triggers}]")
        continue

    # Add a skill
    if user_message.strip().startswith("/skill add "):
        import shlex
        from src.agents.skill_manager import skill_manager
        try:
            parts = shlex.split(user_message)
            # Expected: ['/skill', 'add', 'Name', 'trigger1,trigger2', 'Instruction...']
            if len(parts) < 5:
                print("\nCrusorCodeAI: Usage: /skill add \"Name\" \"triggers\" \"Instruction text\"")
                continue

            name = parts[2]
            triggers = [t.strip() for t in parts[3].split(",")]
            instruction = " ".join(parts[4:])
            skill_manager.add_skill(name, triggers, instruction)
            print(f"\nCrusorCodeAI: ✅ Skill '{name}' added.")
        except Exception as e:
            print(f"\nCrusorCodeAI: Could not parse skill. Error: {e}")
        continue

    # Remove a skill
    if user_message.strip().startswith("/skill remove "):
        from src.agents.skill_manager import skill_manager
        name = user_message[len("/skill remove "):].strip()
        if skill_manager.remove_skill(name):
            print(f"\nCrusorCodeAI: ✅ Skill '{name}' removed.")
        else:
            print(f"\nCrusorCodeAI: Skill '{name}' not found.")
        continue

    # Toggle a skill
    if user_message.strip().startswith("/skill toggle "):
        from src.agents.skill_manager import skill_manager
        name = user_message[len("/skill toggle "):].strip()
        # Check current state
        skills = skill_manager.list_skills()
        target = next((s for s in skills if s["name"] == name), None)
        if target:
            new_state = not target.get("enabled", True)
            skill_manager.toggle_skill(name, new_state)
            status = "enabled" if new_state else "disabled"
            print(f"\nCrusorCodeAI: Skill '{name}' {status}.")
        else:
            print(f"\nCrusorCodeAI: Skill '{name}' not found.")
        continue

    # List sub-agents
    if user_message.strip() == "/agents":
        from src.agents.sub_agent import subagent_coordinator
        agents = subagent_coordinator.list_active()
        if not agents:
            print("\nCrusorCodeAI: No sub-agents spawned yet.")
        else:
            print(f"\nCrusorCodeAI: 🤖 {len(agents)} sub-agent(s):")
            for a in agents:
                print(f"  {a['id']} [{a['mode']}] — {a['task_preview']}...")
        continue

    # Export analytics for dashboard
    if user_message.strip() == "/export":
        import json
        analytics = export_session_analytics(thread_id)
        with open("crusor_analytics.json", "w") as f:
            json.dump(analytics, f, indent=2)
        print("\nCrusorCodeAI: 📊 Analytics exported to crusor_analytics.json")
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

        print(f"\nCrusorCodeAI: {response}")

        # Show token usage for this turn
        status = get_agent_status(thread_id)
        cost = status.get("cost", {})

        if cost.get("calls_made", 0) > 0:
            print(f"\n[Usage] {TokenTracker.format_usage(cost)}")

    except Exception as error:
        print(f"\nCrusorCodeAI Error: {error}")
