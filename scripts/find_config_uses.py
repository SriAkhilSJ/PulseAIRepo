import os

with open(r"c:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo\src\tools\file_tools.py", "r", encoding="utf-8") as f:
    for idx, line in enumerate(f, 1):
        if "configurable" in line or "config[" in line:
            print(f"{idx}: {line.strip()}")

