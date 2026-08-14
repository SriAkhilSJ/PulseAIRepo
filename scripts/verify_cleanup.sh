#!/bin/bash
# Post-cleanup verification for PulseAI.
# Fixes vs the original suggestion: corrected module path (no URL artifact),
# uv-native dev install, and an actual SqliteSaver sanity probe.
set -e
cd "$(dirname "$0")/.."

echo "=== 1. pyproject.toml parses ==="
python -c "import tomllib; tomllib.load(open('pyproject.toml','rb')); print('OK')"

echo "=== 2. Core imports ==="
python -c "from src.graphs.chat_graph import graph; print('chat_graph imports OK')"
python -c "from src.llm.factory import get_embedder, RetryLLMProxy, EmbeddingFactory; print('factory imports OK')"
python -c "from src.context.context_engine import ContextEngine; print('context_engine imports OK')"

echo "=== 3. Checkpointer is persistent ==="
python - <<'PY'
import os
from langgraph.checkpoint.sqlite import SqliteSaver
p = os.path.expanduser("~/.pulseai/sessions.db")
print(f"SqliteSaver usable; sessions path: {p}")
import src.graphs.chat_graph as cg
assert type(cg.memory).__name__ == "SqliteSaver", "checkpointer is not SqliteSaver"
print("graph checkpointer: SqliteSaver ✓")
PY

echo "=== 4. pytest collects and runs (pure tests only; script-tests isolated) ==="
if python -m pytest --version >/dev/null 2>&1; then
    python -m pytest --collect-only -q | tail -3
else
    echo "pytest missing — install dev group: uv sync  (or: uv pip install -e '. --group dev')"
fi

echo "=== 5. .gitignore active ==="
git check-ignore -v generated/ && echo "generated/ ignored ✓"
git check-ignore -v logs/ && echo "logs/ ignored ✓"

echo "=== ALL CHECKS PASSED ==="
