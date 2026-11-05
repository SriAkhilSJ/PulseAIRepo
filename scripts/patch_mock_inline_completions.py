import re

path = 'src/tools/inline_completions.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

target = """        try:
            items = self._call_llm(prompt, request)
        except Exception:
            items = []"""

replacement = """        if os.environ.get("CRUSORAI_DETERMINISTIC_MOCK") == "1":
            items = self._deterministic_mock_completion(request)
        else:
            try:
                items = self._call_llm(prompt, request)
            except Exception:
                items = []"""

mock_method = """
    def _deterministic_mock_completion(self, request: CompletionRequest) -> list[CompletionItem]:
        prefix = request.prefix
        if "add(" in prefix or "return" in prefix:
            text = " return a + b;"
        elif "multiply(" in prefix:
            text = " return a * b;"
        elif "authenticate(" in prefix:
            text = " return Boolean(user && token);"
        else:
            text = " // crusor-auto-complete"

        start_line = request.line
        start_column = request.column
        text_lines = text.splitlines() or [text]
        if len(text_lines) == 1:
            end_line = start_line
            end_column = start_column + len(text)
        else:
            end_line = start_line + len(text_lines) - 1
            end_column = len(text_lines[-1])

        return [CompletionItem(
            text=text,
            range_start_line=start_line,
            range_start_column=start_column,
            range_end_line=end_line,
            range_end_column=end_column,
            confidence=1.0,
            stop_reason="deterministic_mock",
        )]
"""

if target in content and "_deterministic_mock_completion" not in content:
    content = content.replace(target, replacement, 1)
    content = content.replace("    def invalidate(self, resource: str) -> None:", mock_method + "\n    def invalidate(self, resource: str) -> None:", 1)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(content)
    print("Successfully patched inline_completions.py")
else:
    print("Target not found or already patched")

