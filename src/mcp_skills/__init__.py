"""MCP surface for the Architect skill library.

One skill directory = one MCP node. The index is built once from the same
`SkillManager` the internal tools use, so MCP and the in-process tools can never
disagree about what a book says.
"""

from src.mcp_skills.index import Book, SkillIndex, get_index  # noqa: F401
from src.mcp_skills.server import SkillMCPServer  # noqa: F401
