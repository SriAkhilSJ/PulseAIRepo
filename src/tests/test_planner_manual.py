from src.agents.planner import create_plan
from src.config.settings import LLM_PROVIDER, LLM_MODEL


plan = create_plan(
    task=(
        "Add a FastAPI health endpoint "
        "and create a test for it."
    ),
    provider=LLM_PROVIDER,
    model=LLM_MODEL,
)

print(plan.model_dump_json(indent=2))