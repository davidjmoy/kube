#!/bin/bash
# Local testing script - runs analyzer against a subset of k8s code

set -e

REPO_ROOT="${1:-/Users/David/repos/kubernetes}"
OUTPUT_DIR="${2:-./output}"

echo "🧪 Running local code graph analysis test..."
echo "📁 Using repository: $REPO_ROOT"
echo "📂 Output directory: $OUTPUT_DIR"
echo ""

# Check repo exists
if [ ! -d "$REPO_ROOT" ]; then
    echo "❌ Repository not found at $REPO_ROOT"
    echo ""
    echo "Usage: $0 <repo-root> [output-dir]"
    echo ""
    echo "Example:"
    echo "  $0 /path/to/kubernetes ./output"
    exit 1
fi

# Create output dir
mkdir -p "$OUTPUT_DIR"

# Analyze a small package first
echo "1️⃣  Analyzing pkg/client (small test)..."
python main.py analyze \
    --repo-root "$REPO_ROOT" \
    --pkg-dir pkg/client \
    --output "$OUTPUT_DIR/graph-client.json" \
    --stats-output "$OUTPUT_DIR/stats-client.json"

echo ""
echo "2️⃣  Graph statistics:"
jq '.metadata' "$OUTPUT_DIR/stats-client.json" 2>/dev/null || cat "$OUTPUT_DIR/stats-client.json"

echo ""
echo "3️⃣  Sample function analysis..."
python -c "
import json
from pathlib import Path

graph = json.load(open('$OUTPUT_DIR/graph-client.json'))
functions = list(graph['functions'].values())

if functions:
    func = functions[0]
    print(f\"  Function: {func['name']}\")
    print(f\"  Package: {func['package']}\")
    print(f\"  Location: {func['location']['file']}:{func['location']['line']}\")
    print(f\"  Callers: {len(func['callers'])}\")
    print(f\"  Callees: {len(func['callees'])}\")
"

echo ""
echo "✅ Test analysis complete!"
echo ""
echo "Output files:"
echo "  - $OUTPUT_DIR/graph-client.json"
echo "  - $OUTPUT_DIR/stats-client.json"
echo ""
echo "Next steps:"
echo "1. Try different packages: --pkg-dir pkg/api"
echo "2. Query the graph: python main.py find-callers --graph $OUTPUT_DIR/graph-client.json --function NewClient"
echo "3. View all statistics: python examples.py"
