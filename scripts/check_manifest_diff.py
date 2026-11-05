import subprocess
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
diff = subprocess.check_output(["git", "diff", "desktop/SELECTIVE_MANIFEST.json"], cwd=str(repo_root), text=True)
(repo_root / "manifest_diff.txt").write_text(diff, encoding="utf-8")
print("Wrote manifest diff")

