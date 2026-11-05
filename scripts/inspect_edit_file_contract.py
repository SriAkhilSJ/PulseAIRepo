import sys
sys.path.insert(0, ".")
import inspect
from src.tools.file_tools import edit_file, read_file, list_files

print("=== edit_file inspection ===")
print("Signature:", inspect.signature(edit_file.func if hasattr(edit_file, "func") else edit_file))
print("edit_file.args:", edit_file.args)
print("edit_file.args_schema:", edit_file.args_schema.schema() if edit_file.args_schema else None)

print("\n=== read_file inspection ===")
print("read_file.args:", read_file.args)

print("\n=== list_files inspection ===")
print("list_files.args:", list_files.args)

# Test calling edit_file with dictionary
try:
    res = edit_file.invoke({"path": "foo.txt", "old_text": "a", "new_text": "b"})
    print("invoke result:", res)
except Exception as e:
    print("invoke with 3 args failed:", type(e), e)

# Test calling with config inside dict
try:
    res = edit_file.invoke({"path": "foo.txt", "old_text": "a", "new_text": "b", "config": {}})
    print("invoke with config inside dict result:", res)
except Exception as e:
    print("invoke with config inside dict failed:", type(e), e)

# Test calling with config as kwarg
try:
    res = edit_file.invoke({"path": "foo.txt", "old_text": "a", "new_text": "b"}, config={"configurable": {"workspace": "."}})
    print("invoke with config as kwarg result:", res)
except Exception as e:
    print("invoke with config as kwarg failed:", type(e), e)

