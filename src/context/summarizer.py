# src/context/summarizer.py
"""
Smart Summarizer
================

This file compresses long tool outputs so the AI doesn't drown in text.

Think of it like a news editor: the reporter writes 10 pages,
the editor cuts it to 3 paragraphs with only the important facts.
"""

from langchain_core.messages import ToolMessage


class SmartSummarizer:
    """
    Compresses tool outputs before they enter the AI's context.

    RULE: Always try the FREE heuristic first.
    Only use the expensive LLM for truly massive outputs.
    """

    # If a tool output is shorter than this, don't touch it
    SHORT_OUTPUT_LIMIT = 800

    # If it's between this and MAX_LLM_LIMIT, use heuristics
    MAX_HEURISTIC_LIMIT = 3000

    # Only use LLM summarization for truly giant outputs
    MAX_LLM_LIMIT = 8000

    def __init__(self, llm=None):
        """
        llm: Optional LLM instance for smart summarization.
             If None, we only use heuristics (recommended for budget).
        """
        self.llm = llm

    # =========================================================
    # MAIN ENTRY POINT
    # =========================================================

    def summarize_message(self, message: ToolMessage) -> ToolMessage:
        """
        Take a ToolMessage and return a version with compressed content.

        If the content is short, return it unchanged.
        If it's long, return a summarized version.
        """
        content = message.content

        # If content is not a string (sometimes it's a dict/list), convert
        if not isinstance(content, str):
            content = str(content)

        # SHORT: Don't touch it
        if len(content) <= self.SHORT_OUTPUT_LIMIT:
            return message

        # MEDIUM: Use fast heuristics (FREE)
        if len(content) <= self.MAX_HEURISTIC_LIMIT:
            summary = self._heuristic_summarize(
                tool_name=message.name or "unknown",
                content=content,
            )
            return self._replace_content(message, summary)

        # LONG: Use heuristics first, maybe LLM if available
        summary = self._heuristic_summarize(
            tool_name=message.name or "unknown",
            content=content,
        )

        # If we have an LLM and the output is MASSIVE, ask the LLM to summarize
        if self.llm and len(content) > self.MAX_LLM_LIMIT:
            try:
                summary = self._llm_summarize(
                    tool_name=message.name or "unknown",
                    content=content,
                )
            except Exception:
                # If LLM fails, fallback to heuristic summary
                pass

        return self._replace_content(message, summary)

    # =========================================================
    # HEURISTIC SUMMARIZATION (FREE, FAST)
    # =========================================================

    def _heuristic_summarize(self, tool_name: str, content: str) -> str:
        """
        Use pattern-based rules to compress tool output.
        No API calls. No cost. Instant.
        """
        lines = content.splitlines()
        total_lines = len(lines)
        total_chars = len(content)

        # ---- FILE READS ----
        if tool_name in {"read_file", "edit_file"}:
            return self._summarize_file_content(lines, total_lines, total_chars)

        # ---- TERMINAL OUTPUT ----
        if tool_name in {"run_terminal", "check_terminal", "read_terminal_output"}:
            return self._summarize_terminal_output(lines, total_lines, content)

        # ---- SEARCH RESULTS ----
        if tool_name == "search_code":
            return self._summarize_search_results(lines, total_lines)

        # ---- LIST FILES ----
        if tool_name == "list_files":
            return self._summarize_file_list(lines, total_lines)

        # ---- DEFAULT: Smart truncation ----
        return self._default_truncate(lines, total_lines, total_chars)

    def _summarize_file_content(self, lines: list[str], total_lines: int, total_chars: int) -> str:
        """Summarize a file read: show start, end, and key stats."""
        if total_lines <= 50:
            # Small file, just note it's complete
            return f"[File content: {total_lines} lines, {total_chars} chars — shown in full above]"

        # Big file: show first 20 lines + ... + last 10 lines
        first_n = 20
        last_n = 10

        header = f"[File content summarized: {total_lines} lines total]"
        start = "\n".join(lines[:first_n])
        middle = f"\n... ({total_lines - first_n - last_n} lines omitted) ...\n"
        end = "\n".join(lines[-last_n:])

        return f"{header}\n{start}{middle}{end}"

    def _summarize_terminal_output(self, lines: list[str], total_lines: int, content: str) -> str:
        """Summarize terminal output: keep exit code, errors, and last few lines."""
        # Extract exit code if present
        exit_code = None
        if "exit code:" in content.lower():
            try:
                parts = content.lower().split("exit code:")
                code_part = parts[-1].strip().split()[0]
                exit_code = code_part
            except Exception:
                pass

        # Look for error indicators
        has_error = any(keyword in content.lower() for keyword in [
            "error", "traceback", "failed", "exception", "fatal", "cannot"
        ])

        # Keep last 25 lines (most recent output is usually most important)
        last_n = 25
        if total_lines <= last_n:
            summary = content
        else:
            header = f"[Terminal output: {total_lines} lines total]"
            omitted = total_lines - last_n
            body = "\n".join(lines[-last_n:])
            summary = f"{header}\n... ({omitted} earlier lines omitted) ...\n{body}"

        # Add metadata banner
        meta = []
        if exit_code is not None:
            meta.append(f"Exit code: {exit_code}")
        if has_error:
            meta.append("Contains errors")

        if meta:
            summary = f"[{' | '.join(meta)}]\n{summary}"

        return summary

    def _summarize_search_results(self, lines: list[str], total_lines: int) -> str:
        """Summarize search results: keep first 15 matches, count the rest."""
        if total_lines <= 30:
            return "\n".join(lines)

        # Keep first 15 lines (usually ~5 matches with context)
        header = f"[Search results: {total_lines} lines total]"
        preview = "\n".join(lines[:15])
        rest = total_lines - 15

        return f"{header}\n{preview}\n... ({rest} more lines omitted) ..."

    def _summarize_file_list(self, lines: list[str], total_lines: int) -> str:
        """Summarize file listing: count files, show first 20."""
        if total_lines <= 20:
            return "\n".join(lines)

        header = f"[Directory listing: {total_lines} items total]"
        preview = "\n".join(lines[:20])

        return f"{header}\n{preview}\n... ({total_lines - 20} more items) ..."

    def _default_truncate(self, lines: list[str], total_lines: int, total_chars: int) -> str:
        """Default: show first 15 and last 10 lines."""
        if total_lines <= 30:
            return "\n".join(lines)

        header = f"[Output summarized: {total_lines} lines, {total_chars} chars]"
        first = "\n".join(lines[:15])
        middle = f"\n... ({total_lines - 25} lines omitted) ...\n"
        last = "\n".join(lines[-10:])

        return f"{header}\n{first}{middle}{last}"

    # =========================================================
    # LLM SUMMARIZATION (EXPENSIVE — USE SPARINGLY)
    # =========================================================

    def _llm_summarize(self, tool_name: str, content: str) -> str:
        """
        Ask the LLM to summarize a massive output.
        Only called for outputs > 8000 chars.
        """
        if not self.llm:
            raise ValueError("No LLM provided for summarization")

        prompt = f"""
You are a compression assistant. A coding agent just received a very long tool output.

Your job: summarize it in 5-10 lines so the agent knows what happened.

Tool: {tool_name}

Rules:

- Mention the most important facts (errors, results, key findings)

- Mention file names, line numbers, or error messages if relevant

- Do NOT include full code or full output

- Be specific enough that the agent can decide what to do next

Output:
"""
        # Send only the first 4000 chars to the LLM (enough to summarize)
        truncated = content[:4000]

        from langchain_core.messages import HumanMessage, SystemMessage
        response = self.llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content=truncated),
        ])

        summary = str(response.content).strip()
        return f"[LLM-Summarized {tool_name} output]\n{summary}\n[Original was {len(content)} chars]"

    # =========================================================
    # HELPER
    # =========================================================

    def _replace_content(self, message: ToolMessage, new_content: str) -> ToolMessage:
        """Create a new ToolMessage with summarized content."""
        return ToolMessage(
            content=new_content,
            name=message.name,
            tool_call_id=message.tool_call_id,
        )
