import os

p = r"c:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo\src\graphs\task_validation.py"
with open(p, "r", encoding="utf-8") as f:
    text = f.read()

# Normalize newlines for matching
text_crlf = "\r\n" in text
text_norm = text.replace("\r\n", "\n")

old_config_patterns = '''    config_file_patterns = [
        r"\\.env(?:\\.example)?\\b",
        r"\\bsettings\\.py\\b",
        r"\\b(?:src/)?database\\.py\\b",
        r"\\b(?:src/)?db\\.py\\b",
        r"\\bfinancial_store\\.py\\b",
        r"\\brate_limits\\.db\\b",
    ]'''

new_config_patterns = '''    config_file_patterns = [
        r"(?:src/)?(?:config/)?(?:db|settings|database)\\.py\\b",
        r"\\.env(?:\\.(?:example|local|production|test|dev))?\\b",
        r"(?:src/(?:agents/)?)?financial_store\\.py\\b",
        r"\\brate_limits\\.db\\b",
        r"(?:src/)?(?:core/)?config\\.py\\b",
    ]'''

# Let's find config_file_patterns in text_norm
import re
pattern = r"    config_file_patterns = \[\n(?:        [^\n]+\n)+    \]"
assert re.search(pattern, text_norm), "Regex pattern for config_file_patterns not found"
text_norm = re.sub(pattern, new_config_patterns, text_norm)

if text_crlf:
    text_norm = text_norm.replace("\n", "\r\n")

with open(p, "w", encoding="utf-8") as f:
    f.write(text_norm)

print("Updated config_file_patterns in task_validation.py successfully!")
