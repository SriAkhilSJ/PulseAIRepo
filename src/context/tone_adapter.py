
"""
Tone Adapter for PulseCodeAI
=============================
Analyzes the current task and adjusts the agent's communication style.
Simple tasks get casual, fast responses. Complex tasks get thorough,
structured explanations.

What this changes:
- The agent feels more intelligent and context-aware
- Casual requests don't get over-engineered responses
- Complex architecture tasks get the depth they deserve
"""

from typing import Literal

class ToneAdapter:
    """
    Adapts the agent's tone based on task complexity.
    """

    def classify_task(self, task: str) -> Literal["simple", "standard", "complex"]:
        """
        Classify task complexity based on keywords and length.
        """
        task_lower = task.lower()

        # Simple: one-liners, quick lookups, trivial changes
        simple_signals = [
            "hello", "hi ", "what is", "how do i", "explain", "show me",
            "list ", "find ", "where is", "print ", "create a simple",
            "quick ", "just ", "only ", "count ", "sum ", "sort ",
        ]

        if any(s in task_lower for s in simple_signals) and len(task) < 80:
            return "simple"

        # Complex: architecture, design, refactoring, multi-file
        complex_signals = [
            "architecture", "design", "refactor", "redesign", "restructure",
            "migrate", "implement", "build a", "create a system",
            "set up", "configure", "integrate", "microservice", "api design",
            "database schema", "authentication", "authorization", "caching",
            "performance", "optimization", "security", "testing strategy",
            "deployment", "ci/cd", "docker", "kubernetes",
        ]

        if any(c in task_lower for c in complex_signals) or len(task) > 300:
            return "complex"

        return "standard"

    def get_tone_guidelines(self, task: str) -> str:
        """
        Return tone-specific instructions for the agent.
        """
        tone = self.classify_task(task)

        if tone == "simple":
            return (
                "=== TONE: CASUAL & FAST ===\n"
                "This looks like a quick request. Keep your response:\n"
                "- Brief and to the point\n"
                "- Friendly but not overly formal\n"
                "- Skip lengthy explanations unless asked\n"
                "- One or two sentences for the summary is fine\n"
            )

        if tone == "complex":
            return (
                "=== TONE: THOROUGH & STRUCTURED ===\n"
                "This looks like a complex or architectural task. Keep your response:\n"
                "- Start with a high-level overview of your approach\n"
                "- Explain trade-offs and design decisions\n"
                "- Use headers and sections for readability\n"
                "- Include verification steps and edge-case handling\n"
                "- Warn about potential risks before making changes\n"
                "- Summarize what was done and why at the end\n"
            )

        # standard
        return (
            "=== TONE: BALANCED ===\n"
            "This is a standard coding task. Keep your response:\n"
            "- Clear and well-structured\n"
            "- Explain the 'what' and a brief 'why'\n"
            "- Use markdown for code and file paths\n"
            "- Verify your work before reporting success\n"
        )
