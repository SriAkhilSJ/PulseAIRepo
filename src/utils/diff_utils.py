"""Unified diff computation -- NEUTRAL module.

Moved out of chat_graph (round-12 review): a TOOL importing the GRAPH is an
inverted dependency (tools -> graph -> tools cycle and un-testable tools).
Both chat_graph and file_tools now import from here.
"""

def compute_unified_diff(old_content: str, new_content: str, file_path: str) -> dict:
    """
    Compute a unified diff between old and new file content.
    Returns a dict that the dashboard can render.
    """
    import difflib
    import time
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=file_path, tofile=file_path,
        lineterm="",
    ))

    # Parse into chunks
    chunks = []
    current_chunk = None
    chunk_id = 0
    for line in diff:
        if line.startswith("@@"):
            if current_chunk:
                chunks.append(current_chunk)
            # Parse @@ -start,count +start,count @@
            parts = line.split("@@")[1].strip()
            old_part, new_part = parts.split(" +")
            old_start = int(old_part.split(",")[0].replace("-", ""))
            old_count = int(old_part.split(",")[1]) if "," in old_part else 1
            new_start = int(new_part.split(",")[0])
            new_count = int(new_part.split(",")[1]) if "," in new_part else 1
            
            chunk_id += 1
            current_chunk = {
                "chunk_id": f"chunk-{chunk_id}",
                "old_start": old_start,
                "old_lines": old_count,
                "new_start": new_start,
                "new_lines": new_count,
                "lines": [],
            }
        elif current_chunk is not None:
            if line.startswith("+"):
                current_chunk["lines"].append({
                    "type": "added",
                    "old_no": None,
                    "new_no": current_chunk["new_start"] + len([l for l in current_chunk["lines"] if l["type"] in ("added", "context")]),
                    "text": line[1:],
                })
            elif line.startswith("-"):
                current_chunk["lines"].append({
                    "type": "removed",
                    "old_no": current_chunk["old_start"] + len([l for l in current_chunk["lines"] if l["type"] in ("removed", "context")]),
                    "new_no": None,
                    "text": line[1:],
                })
            elif line.startswith(" "):
                current_chunk["lines"].append({
                    "type": "context",
                    "old_no": current_chunk["old_start"] + len([l for l in current_chunk["lines"] if l["type"] in ("removed", "context")]),
                    "new_no": current_chunk["new_start"] + len([l for l in current_chunk["lines"] if l["type"] in ("added", "context")]),
                    "text": line[1:],
                })

    if current_chunk:
        chunks.append(current_chunk)

    return {
        "diff_id": f"diff-{int(time.time() * 1000)}",
        "file": file_path,
        "old_path": file_path,
        "new_path": file_path,
        "chunks": chunks,
    }

# =========================================================
# SYSTEM PROMPT
# =========================================================
