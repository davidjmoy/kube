"""Quick script to check what's in the current code graph."""
import json
from collections import Counter

d = json.load(open("output/code-graph.json"))
m = d["metadata"]

print("=== Current Graph Coverage ===")
print(f"Packages:  {len(m['packages'])}")
print(f"Functions: {m['total_functions']}")
print(f"Types:     {m['total_types']}")
print(f"Calls:     {m['total_calls']}")

# Show which top-level dirs are covered
dirs = Counter()
for f in d["functions"].values():
    p = f["location"]["file"]
    parts = p.split("/")
    if len(parts) >= 2:
        dirs[parts[0] + "/" + parts[1]] += 1

print(f"\nSource directories in graph ({len(dirs)} subdirs):")
for path, count in dirs.most_common(40):
    print(f"  {path:55s} {count:5d} functions")
