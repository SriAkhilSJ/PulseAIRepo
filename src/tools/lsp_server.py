"""LSP (Language Server Protocol) server for PulseAI.

Wraps the existing tree-sitter and Python AST analysis into a standard
LSP server. This gives VSCode code intelligence (go-to-definition,
find-references, document symbols, etc.) powered by PulseAI's code
understanding capabilities.

The server runs as a separate process and communicates via stdio
(JSON-RPC 2.0), which is the standard LSP transport.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from typing import Any, Optional


class LSPServer:
    """Minimal LSP server that wraps PulseAI's code analysis capabilities.
    
    Implements the core LSP methods needed for code intelligence:
    - initialize: Server capabilities
    - textDocument/didOpen: Track open documents
    - textDocument/didChange: Track document changes
    - textDocument/documentSymbol: Document symbols
    - textDocument/definition: Go to definition
    - textDocument/references: Find references
    - textDocument/hover: Hover information
    """

    def __init__(self):
        self._documents: dict[str, dict] = {}
        self._workspace: str = ""
        self._initialized = False
        self._lock = threading.Lock()

    def run(self) -> int:
        """Run the LSP server on stdin/stdout."""
        try:
            while True:
                line = sys.stdin.readline()
                if not line:
                    break

                # Parse Content-Length header
                if line.startswith("Content-Length:"):
                    content_length = int(line.split(":")[1].strip())
                    sys.stdin.readline()  # Empty line
                    body = sys.stdin.read(content_length)
                    self._handle_message(json.loads(body))
        except Exception:
            return 1
        return 0

    def _handle_message(self, message: dict) -> None:
        """Handle an incoming JSON-RPC message."""
        method = message.get("method", "")
        msg_id = message.get("id")
        params = message.get("params", {})

        if method == "initialize":
            self._handle_initialize(msg_id, params)
        elif method == "initialized":
            self._initialized = True
        elif method == "shutdown":
            self._send_response(msg_id, None)
            sys.exit(0)
        elif method == "exit":
            sys.exit(0)
        elif method == "textDocument/didOpen":
            self._handle_did_open(params)
        elif method == "textDocument/didChange":
            self._handle_did_change(params)
        elif method == "textDocument/didClose":
            self._handle_did_close(params)
        elif method == "textDocument/documentSymbol":
            self._handle_document_symbol(msg_id, params)
        elif method == "textDocument/definition":
            self._handle_definition(msg_id, params)
        elif method == "textDocument/references":
            self._handle_references(msg_id, params)
        elif method == "textDocument/hover":
            self._handle_hover(msg_id, params)

    def _handle_initialize(self, msg_id: int | None, params: dict) -> None:
        """Handle initialize request — return server capabilities."""
        self._workspace = params.get("rootPath", "") or params.get("rootUri", "")
        if self._workspace.startswith("file://"):
            self._workspace = self._workspace[7:]

        capabilities = {
            "textDocumentSync": 1,  # Full sync
            "documentSymbolProvider": True,
            "definitionProvider": True,
            "referencesProvider": True,
            "hoverProvider": True,
        }

        result = {
            "capabilities": capabilities,
            "serverInfo": {
                "name": "pulseai-lsp",
                "version": "0.1.0",
            },
        }

        self._send_response(msg_id, result)

    def _handle_did_open(self, params: dict) -> None:
        """Track newly opened documents."""
        text_document = params.get("textDocument", {})
        uri = text_document.get("uri", "")
        with self._lock:
            self._documents[uri] = {
                "uri": uri,
                "languageId": text_document.get("languageId", ""),
                "version": text_document.get("version", 0),
                "text": text_document.get("text", ""),
            }

    def _handle_did_change(self, params: dict) -> None:
        """Track document changes."""
        text_document = params.get("textDocument", {})
        uri = text_document.get("uri", "")
        with self._lock:
            if uri in self._documents:
                self._documents[uri]["text"] = params.get("contentChanges", [{}])[-1].get("text", "")
                self._documents[uri]["version"] = text_document.get("version", 0)

    def _handle_did_close(self, params: dict) -> None:
        """Remove closed documents."""
        uri = params.get("textDocument", {}).get("uri", "")
        with self._lock:
            self._documents.pop(uri, None)

    def _handle_document_symbol(self, msg_id: int | None, params: dict) -> None:
        """Return document symbols using tree-sitter analysis."""
        uri = params.get("textDocument", {}).get("uri", "")
        with self._lock:
            doc = self._documents.get(uri)

        if not doc:
            self._send_response(msg_id, [])
            return

        symbols = self._extract_symbols(doc)
        self._send_response(msg_id, symbols)

    def _handle_definition(self, msg_id: int | None, params: dict) -> None:
        """Find definition location using code analysis."""
        uri = params.get("textDocument", {}).get("uri", "")
        position = params.get("position", {})
        line = position.get("line", 0)
        character = position.get("character", 0)

        with self._lock:
            doc = self._documents.get(uri)

        if not doc:
            self._send_response(msg_id, None)
            return

        # Get the word at cursor
        text = doc.get("text", "")
        lines = text.split("\n")
        if line >= len(lines):
            self._send_response(msg_id, None)
            return

        current_line = lines[line]
        word = self._get_word_at(current_line, character)
        if not word:
            self._send_response(msg_id, None)
            return

        # Search for definition in the workspace
        definition = self._find_definition(word, uri)
        self._send_response(msg_id, definition)

    def _handle_references(self, msg_id: int | None, params: dict) -> None:
        """Find all references to a symbol."""
        uri = params.get("textDocument", {}).get("uri", "")
        position = params.get("position", {})
        line = position.get("line", 0)
        character = position.get("character", 0)

        with self._lock:
            doc = self._documents.get(uri)

        if not doc:
            self._send_response(msg_id, [])
            return

        text = doc.get("text", "")
        lines = text.split("\n")
        if line >= len(lines):
            self._send_response(msg_id, [])
            return

        current_line = lines[line]
        word = self._get_word_at(current_line, character)
        if not word:
            self._send_response(msg_id, [])
            return

        references = self._find_references(word, uri)
        self._send_response(msg_id, references)

    def _handle_hover(self, msg_id: int | None, params: dict) -> None:
        """Provide hover information about a symbol."""
        uri = params.get("textDocument", {}).get("uri", "")
        position = params.get("position", {})
        line = position.get("line", 0)
        character = position.get("character", 0)

        with self._lock:
            doc = self._documents.get(uri)

        if not doc:
            self._send_response(msg_id, None)
            return

        text = doc.get("text", "")
        lines = text.split("\n")
        if line >= len(lines):
            self._send_response(msg_id, None)
            return

        current_line = lines[line]
        word = self._get_word_at(current_line, character)
        if not word:
            self._send_response(msg_id, None)
            return

        hover = self._get_hover_info(word, uri)
        self._send_response(msg_id, hover)

    def _extract_symbols(self, doc: dict) -> list[dict]:
        """Extract document symbols using language-specific analysis."""
        language_id = doc.get("languageId", "")
        text = doc.get("text", "")

        if language_id == "python":
            return self._extract_python_symbols(text)
        elif language_id in ("typescript", "javascript", "typescriptreact", "javascriptreact"):
            return self._extract_js_symbols(text)
        else:
            return self._extract_generic_symbols(text)

    def _extract_python_symbols(self, text: str) -> list[dict]:
        """Extract Python symbols using AST."""
        import ast
        symbols = []
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    symbols.append({
                        "name": node.name,
                        "kind": 12,  # Function
                        "range": {
                            "start": {"line": node.lineno - 1, "character": node.col_offset},
                            "end": {"line": node.end_lineno - 1 if node.end_lineno else node.lineno - 1, "character": node.end_col_offset if node.end_col_offset else 0},
                        },
                        "selectionRange": {
                            "start": {"line": node.lineno - 1, "character": node.col_offset},
                            "end": {"line": node.lineno - 1, "character": node.col_offset + len(node.name)},
                        },
                    })
                elif isinstance(node, ast.ClassDef):
                    symbols.append({
                        "name": node.name,
                        "kind": 5,  # Class
                        "range": {
                            "start": {"line": node.lineno - 1, "character": node.col_offset},
                            "end": {"line": node.end_lineno - 1 if node.end_lineno else node.lineno - 1, "character": node.end_col_offset if node.end_col_offset else 0},
                        },
                        "selectionRange": {
                            "start": {"line": node.lineno - 1, "character": node.col_offset},
                            "end": {"line": node.lineno - 1, "character": node.col_offset + len(node.name)},
                        },
                    })
        except SyntaxError:
            pass
        return symbols

    def _extract_js_symbols(self, text: str) -> list[dict]:
        """Extract JS/TS symbols using regex (lightweight fallback)."""
        symbols = []
        import re
        for match in re.finditer(r"(?:function|const|let|var|class)\s+(\w+)", text):
            name = match.group(1)
            line = text[:match.start()].count("\n")
            symbols.append({
                "name": name,
                "kind": 12,  # Function (generic)
                "range": {
                    "start": {"line": line, "character": 0},
                    "end": {"line": line, "character": len(match.group(0))},
                },
                "selectionRange": {
                    "start": {"line": line, "character": match.group(0).index(name)},
                    "end": {"line": line, "character": match.group(0).index(name) + len(name)},
                },
            })
        return symbols

    def _extract_generic_symbols(self, text: str) -> list[dict]:
        """Extract generic symbols using regex."""
        import re
        symbols = []
        for match in re.finditer(r"^(?:def|function|class|func|proc|method)\s+(\w+)", text, re.MULTILINE):
            name = match.group(1)
            line = text[:match.start()].count("\n")
            symbols.append({
                "name": name,
                "kind": 12,
                "range": {
                    "start": {"line": line, "character": 0},
                    "end": {"line": line, "character": len(match.group(0))},
                },
                "selectionRange": {
                    "start": {"line": line, "character": match.group(0).index(name)},
                    "end": {"line": line, "character": match.group(0).index(name) + len(name)},
                },
            })
        return symbols

    def _get_word_at(self, line: str, character: int) -> str | None:
        """Get the word at a given character position."""
        if character > len(line):
            return None
        # Expand from cursor position
        start = character
        while start > 0 and (line[start - 1].isalnum() or line[start - 1] == "_"):
            start -= 1
        end = character
        while end < len(line) and (line[end].isalnum() or line[end] == "_"):
            end += 1
        word = line[start:end]
        return word if word else None

    def _find_definition(self, word: str, current_uri: str) -> dict | None:
        """Find the definition of a symbol in open documents."""
        with self._lock:
            for uri, doc in self._documents.items():
                text = doc.get("text", "")
                language_id = doc.get("languageId", "")

                if language_id == "python":
                    import ast
                    try:
                        tree = ast.parse(text)
                        for node in ast.walk(tree):
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                                if node.name == word:
                                    return {
                                        "uri": uri,
                                        "range": {
                                            "start": {"line": node.lineno - 1, "character": node.col_offset},
                                            "end": {"line": node.lineno - 1, "character": node.col_offset + len(node.name)},
                                        },
                                    }
                    except SyntaxError:
                        pass
                else:
                    import re
                    pattern = rf"(?:function|class|const|let|var)\s+{re.escape(word)}\b"
                    match = re.search(pattern, text)
                    if match:
                        line = text[:match.start()].count("\n")
                        col = match.start() - text.rfind("\n", 0, match.start()) - 1
                        return {
                            "uri": uri,
                            "range": {
                                "start": {"line": line, "character": col},
                                "end": {"line": line, "character": col + len(match.group(0))},
                            },
                        }
        return None

    def _find_references(self, word: str, current_uri: str) -> list[dict]:
        """Find all references to a symbol."""
        references = []
        with self._lock:
            for uri, doc in self._documents.items():
                text = doc.get("text", "")
                lines = text.split("\n")
                for line_num, line in enumerate(lines):
                    col = 0
                    while True:
                        idx = line.find(word, col)
                        if idx == -1:
                            break
                        # Check it's a whole word
                        before = idx > 0 and (line[idx - 1].isalnum() or line[idx - 1] == "_")
                        after = idx + len(word) < len(line) and (line[idx + len(word)].isalnum() or line[idx + len(word)] == "_")
                        if not before and not after:
                            references.append({
                                "uri": uri,
                                "range": {
                                    "start": {"line": line_num, "character": idx},
                                    "end": {"line": line_num, "character": idx + len(word)},
                                },
                            })
                        col = idx + 1
        return references

    def _get_hover_info(self, word: str, current_uri: str) -> dict | None:
        """Get hover information for a symbol."""
        with self._lock:
            doc = self._documents.get(current_uri)
            if not doc:
                return None

            text = doc.get("text", "")
            language_id = doc.get("languageId", "")

            if language_id == "python":
                import ast
                try:
                    tree = ast.parse(text)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef) and node.name == word:
                            args = [arg.arg for arg in node.args.args]
                            return {
                                "contents": {
                                    "kind": "markdown",
                                    "value": f"```python\ndef {word}({', '.join(args)})\n```\n\nFunction definition at line {node.lineno}",
                                },
                            }
                        elif isinstance(node, ast.ClassDef) and node.name == word:
                            return {
                                "contents": {
                                    "kind": "markdown",
                                    "value": f"```python\nclass {word}\n```\n\nClass definition at line {node.lineno}",
                                },
                            }
                except SyntaxError:
                    pass

        return None

    def _send_response(self, msg_id: int | None, result: Any) -> None:
        """Send a JSON-RPC response."""
        if msg_id is None:
            return
        response = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": result,
        }
        body = json.dumps(response)
        sys.stdout.write(f"Content-Length: {len(body)}\r\n\r\n{body}")
        sys.stdout.flush()


def main() -> int:
    """Entry point for the LSP server process."""
    return LSPServer().run()


if __name__ == "__main__":
    raise SystemExit(main())
