p = r"c:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo\src\tools\file_tools.py"
with open(p, "r", encoding="utf-8") as f:
    text = f.read()

old = 'elif "not found" in err_lower:'
new = 'elif "not found" in err_lower or "not find" in err_lower or "could not find" in err_lower:'
assert old in text, "Target not found"
text = text.replace(old, new, 1)

with open(p, "w", encoding="utf-8") as f:
    f.write(text)
print("Updated file_tools.py successfully!")

