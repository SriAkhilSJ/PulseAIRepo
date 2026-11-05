from pathlib import Path
content = Path("test_run.log").read_text(encoding="utf-16le", errors="replace")
Path("test_run_utf8.log").write_text(content, encoding="utf-8")
print("Converted log")

