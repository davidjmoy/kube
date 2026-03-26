# Quick Start Guide - Code Graph Builder

## Project Overview

You now have a complete Roslyn-style code graph builder for Kubernetes (or any Go) source code. This system enables:

- 🔍 **Semantic Code Analysis** - Parse Go code into structured AST
- 🕸️ **Call Graph Construction** - Track who calls what function
- 📊 **Type & Interface Analysis** - Understand type relationships  
- 💾 **JSON Graph Export** - Machine-readable code representation
- 🤖 **LLM Integration** - Feed into AI systems for question answering
- ☁️ **Cloud Deployment** - Run on AKS with included K8s manifests

## What Was Built

```
code-graph-builder/
├── src/parser/           # Go code parsing engine
│   ├── go_parser.py     # Main parser (tree-sitter based)
│   └── ast_visitor.py   # AST traversal & extraction
├── src/graph/            # Core data structures
│   ├── code_graph.py    # Graph model (functions, types, calls)
│   └── json_encoder.py  # Serialization
├── src/query/            # Analysis engine
│   └── graph_query.py   # Query interface (callers, callees, paths)
├── src/api_service.py   # FastAPI REST backend
├── main.py              # CLI application
├── examples.py          # Usage examples
├── requirements.txt     # Python dependencies
├── Dockerfile           # Docker image
├── k8s-deployment.yaml # Kubernetes Job template
└── README.md            # Full documentation
```

## Installation (5 minutes)

### Option 1: Local Setup (Linux/Mac/Windows)

```bash
cd c:\Users\david\repos\kube\code-graph-builder

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or: venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Verify installation
python main.py --help
```

### Option 2: Docker Setup

```bash
cd code-graph-builder
docker build -t code-graph-builder .
docker run --rm code-graph-builder python main.py --help
```

## Getting Started (3 commands)

### Step 1: Analyze a Small Package (2-3 minutes)

```bash
python main.py analyze \
  --repo-root c:\Users\david\repos\kubernetes \
  --pkg-dir pkg/client \
  --output output/graph.json \
  --stats-output output/stats.json
```

**Watch For:**
- ✅ "Parsed XXX Go files"
- ✅ Graph statistics showing functions, types, calls
- ✅ Output files created in `output/` directory

### Step 2: Query the Graph

```bash
# Find callers of NewClient function
python main.py find-callers \
  --graph output/graph.json \
  --function NewClient

# View graph statistics  
python main.py analyze-graph \
  --graph output/graph.json \
  --top-n 30
```

### Step 3: Use Programmatically (Python)

```python
from src.graph import CodeGraphSerializer
from src.query import GraphQuery

# Load graph
graph_data = CodeGraphSerializer.load_graph(Path('output/graph.json'))
functions = graph_data['functions']

# Find a function
target = [f for f in functions.values() if f['name'] == 'NewClient'][0]

# See who calls it
print(f"Direct callers: {target['callers']}")
print(f"Calls: {target['callees']}")

# Answer: "Who calls NewClient?"
```

## JSON Output Format

The generated `graph.json` is queryable:

```json
{
  "version": "1.0",
  "metadata": {
    "total_functions": 5000,
    "total_types": 1200,
    "total_calls": 45000
  },
  "functions": {
    "pkg/client/client.go:client:NewClient": {
      "name": "NewClient",
      "package": "client",
      "location": {"file": "pkg/client/client.go", "line": 42},
      "callers": ["pkg/main.go:main:main"],
      "callees": ["pkg/client/client.go:client:validate"]
    }
  }
}
```

## Next Steps

### 1. Expand Analysis Scope

Start small, then expand:

```bash
# Analyze multiple packages
python main.py analyze --repo-root c:\Users\david\repos\kubernetes --pkg-dir pkg/api
python main.py analyze --repo-root c:\Users\david\repos\kubernetes --pkg-dir pkg/controller

# Full repository (takes 5-10 min, uses 2-4GB RAM)
python main.py analyze --repo-root c:\Users\david\repos\kubernetes
```

### 2. Build Chatbot Backend

Create a backend service:

```bash
# Install FastAPI
pip install fastapi uvicorn

# Start API server
uvicorn src.api_service:app --reload --port 8000

# Test endpoint
curl http://localhost:8000/functions/search?name=NewClient
curl http://localhost:8000/metadata
curl http://localhost:8000/stats
```

API endpoints include:
- `GET /metadata` - Graph metadata
- `GET /stats` - Detailed statistics
- `GET /functions/search?name=XXX` - Find functions
- `GET /functions/{id}/callers` - Get callers
- `GET /functions/{id}/callees` - Get callees
- `GET /analyze/critical-functions` - Most-called functions
- `GET /analyze/entry-points` - Public APIs
- `GET /types/search?name=XXX` - Find types

### 3. Deploy to AKS

```bash
# Build Docker image
docker build -t myregistry.azurecr.io/code-graph-builder:v1 .
docker push myregistry.azurecr.io/code-graph-builder:v1

# Deploy to AKS
kubectl apply -f k8s-deployment.yaml

# Monitor
kubectl logs job/code-graph-analysis
kubectl get job code-graph-analysis
```

### 4. Integrate with LLM

```python
from src.graph import CodeGraphSerializer

def build_llm_context(function_name: str):
    """Build context about a function for LLM."""
    graph = CodeGraphSerializer.load_graph(Path('output/graph.json'))
    functions = graph['functions']
    
    # Find function
    func = next(
        (f for f in functions.values() if f['name'] == function_name),
        None
    )
    
    if not func:
        return f"Function {function_name} not found"
    
    # Build context
    return {
        'function': func['name'],
        'location': f"{func['location']['file']}:{func['location']['line']}",
        'signature': func['signature'],
        'who_calls_it': len(func['callers']),
        'what_it_calls': len(func['callees']),
        'documentation': func.get('doc', 'None'),
        'callers_example': functions.get(func['callers'][0], {}).get('name') if func['callers'] else None,
    }

# Use with LLM
context = build_llm_context('NewClient')
prompt = f"Based on this code context: {context}, answer user question..."
```

## Performance Tips

### Start Small
```bash
# First analysis - pick one package
python main.py analyze --repo-root ... --pkg-dir pkg/client
```

### Exclude Large Subdirectories
The parser automatically skips:
- `vendor/` - Third-party code
- `third_party/` - External dependencies
- `*_test.go` - Test files
- `*_generated.go` - Generated code

### Monitor Memory
- Small package (1-2K functions): ~200MB
- Medium package (5-10K functions): ~1GB
- Full k8s repo (50K+ functions): ~4GB

## Troubleshooting

### ImportError: No module named 'tree_sitter'
```bash
pip install -r requirements.txt
```

### Tree-sitter compilation error (Windows)
Install Visual Studio Build Tools:
- Download from https://visualstudio.microsoft.com/downloads/
- Install C++ Build Tools
- Re-run pip install

### Out of memory
Use a machine with more RAM or analyze smaller packages incrementally:
```bash
for pkg in pkg/client pkg/api pkg/controller; do
  python main.py analyze --repo-root ... --pkg-dir $pkg
done
```

### Slow analysis
- Check CPU/memory usage
- Start with smaller packages
- Pre-filter directory with `--pkg-dir`

## Examples

Run all examples:
```bash
python examples.py
```

Individual examples:
- `example_basic_usage()` - Find functions and callers
- `example_query_interface()` - Complex queries
- `example_chatbot_context()` - Build LLM context
- `example_critical_paths()` - Find critical functions
- `example_impact_analysis()` - Impact of changes

## File Locations

- **Kubernetes source**: `c:\Users\david\repos\kubernetes`
- **Project directory**: `c:\Users\david\repos\kube\code-graph-builder`
- **Output files**: `code-graph-builder\output\`
- **Configuration**: `code-graph-builder\requirements.txt`

## Next Session: Advanced Features

Future enhancements to implement:
- Cross-package reference resolution
- Interface implementation tracking
- Goroutine concurrency analysis
- Go module dependency graph
- Call chain optimization detection
- Neo4j/GraphQL backend
- Web-based visualization

## Support

Full documentation: See `README.md` in project root

Questions about features or usage - check `examples.py` for code samples.

---

**You're ready to go!** Start with:
```bash
python main.py analyze --repo-root c:\Users\david\repos\kubernetes --pkg-dir pkg/client
```

Then check the output and query it. Happy analyzing! 🚀
