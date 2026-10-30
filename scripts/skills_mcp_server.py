#!/usr/bin/env python3
"""Entry point: run the Architect skill library as an MCP stdio server.

    python scripts/skills_mcp_server.py

Example `.crusorai/mcp.json` entry:

    {
      "servers": {
        "skills": {
          "command": ["python", "scripts/skills_mcp_server.py"],
          "enabled": true
        }
      }
    }
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.mcp_skills.server import main  # noqa: E402

if __name__ == "__main__":
    main()
