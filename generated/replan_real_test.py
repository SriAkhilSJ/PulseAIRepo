from pathlib import Path

input_file = Path("generated/source_data.txt")
output_file = Path("generated/replan_result.txt")

data = input_file.read_text()
output_file.write_text(data.upper())

print("Replan result created")