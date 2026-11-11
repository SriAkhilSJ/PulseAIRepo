"""UTF-8 reliability across gateway, protocol, broker and file tools."""
from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import AIMessage

from src.bridge.protocol import decode_line, encode
from src.llm.gateway import invoke_model, new_invocation_context
from src.tools.file_tools import edit_file, write_file
from src.workspace.mutation_broker import WorkspaceMutationBroker

TEXT = (
    "Crusor — Build and Ship with Ease 🚀\n"
    "क्रूसोर — आसान और भरोसेमंद\n"
    "日本語：開発を加速する\n"
    "“Quotes”, ‘apostrophes’, backslash \\\\ and dash – done.\n"
)


def test_protocol_round_trips_unicode_exactly() -> None:
    frame = {"type": "token", "text": TEXT, "session_id": "s-🚀"}
    raw = encode(frame)
    assert raw.endswith(b"\n")
    decoded = decode_line(raw)
    assert decoded["text"] == TEXT
    assert decoded["session_id"] == "s-🚀"


def test_gateway_preserves_unicode_text() -> None:
    class Fake:
        def invoke(self, messages, config=None, **kwargs):
            return AIMessage(content=TEXT)

    result = invoke_model(
        Fake(), "prompt", context=new_invocation_context(session_id="s")
    )
    assert result.text == TEXT


def test_broker_writes_exact_utf8_bytes(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    broker = WorkspaceMutationBroker(str(ws))
    broker.create_file(path="unicode.md", content=TEXT, task_id="u")
    raw = (ws / "unicode.md").read_bytes()
    assert raw == TEXT.encode("utf-8")
    assert raw.decode("utf-8") == TEXT
    assert b"\r\n" not in raw


def test_file_tools_write_and_edit_preserve_utf8(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    config = {"configurable": {"workspace": str(ws), "thread_id": "utf8"}}
    out = write_file.func(path="notes.md", content=TEXT, config=config)
    assert "File written" in out
    assert (ws / "notes.md").read_bytes() == TEXT.encode("utf-8")

    edited = TEXT.replace("Ease 🚀", "Ease 🚀 (edited)")
    out = edit_file.func(path="notes.md", old_text=TEXT, new_text=edited, config=config)
    assert "lines added" in out or "edited" in out or "Updated" in out
    assert (ws / "notes.md").read_bytes() == edited.encode("utf-8")
