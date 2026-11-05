import subprocess
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
out = subprocess.check_output(["git", "status", "--porcelain"], cwd=str(repo_root), text=True)
(repo_root / "git_status_utf8.txt").write_text(out, encoding="utf-8")
print("Wrote git status")

