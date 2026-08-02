from pathlib import Path

source = Path("generated/definitely_missing_remote_data.txt")
local_source = Path("generated/replan_local_source.txt")
output = Path("generated/replan_recovery_output.txt")

if source.exists():
    data = source.read_text(encoding='utf-8')
    data_source = "remote"
else:
    # Original remote data source is permanently unavailable;
    # recover using the available local source.
    data = local_source.read_text(encoding='utf-8')
    data_source = "local fallback (generated/replan_local_source.txt)"

output.write_text(data, encoding='utf-8')
print(f"Recovery complete (source: {data_source})")
