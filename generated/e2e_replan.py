from pathlib import Path

source = Path(__file__).parent / "source_data.txt"

if not source.exists():
    raise RuntimeError(
        "Required local data source is unavailable."
    )

print(source.read_text())