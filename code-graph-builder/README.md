# Code Graph Builder for Kubernetes

An AI-powered code assistant for the Kubernetes codebase. Combines a Roslyn-style call graph, full-text source search, and Kubernetes documentation search — all exposed to GPT-4o as tool calls for multi-step reasoning over 45k+ functions.

## Features

- **Streaming AI Chat** — GPT-4o with tool calling, streamed via SSE to a browser UI
- **Code Graph** — 45,821 functions, 25,649 types, 119,209 call edges parsed with tree-sitter
- **Source Search** — SQLite FTS5 index over 11,463 Go source files (~549 MB)
- **Doc Search** — SQLite FTS5 index over 1,570 Kubernetes documentation pages
- **7 LLM Tools** — `grep_code`, `read_file`, `find_callers`, `search_graph`, `list_directory`, `search_docs`, `read_doc`
- **GitHub Links** — Source references render as clickable links to github.com/kubernetes/kubernetes
- **Cloud Deployment** — Terraform IaC for AKS, ACR, Azure OpenAI; tear down/rebuild for cost control
- **Local Dev** — Docker Compose, Minikube, or bare `uvicorn`

## Quick Start (Local)

```bash
# 1. Clone and set up
cd code-graph-builder
python -m venv venv
venv\Scripts\activate        # Linux/macOS: source venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env         # Edit with your Azure OpenAI credentials

# 3. Build indexes (first time only, ~10 min)
python main.py analyze --repo-root /path/to/kubernetes --output output/code-graph-full.json

# 4. Run
uvicorn src.chatbot_service:app --host 0.0.0.0 --port 8000 --reload
# Open http://localhost:8000
```

The chatbot service auto-builds the file and doc indexes on first startup if they don't exist.

## Cloud Deployment (AKS)

All costly infrastructure is managed by Terraform for easy teardown/rebuild:

```powershell
# Stand up infrastructure (~15 min)
cd terraform
terraform init
terraform apply

# Build image and deploy to AKS
cd ..
.\scripts\rebuild.ps1

# Tear down when not in use (~$400/mo savings)
.\scripts\teardown.ps1
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for full infrastructure details.

## CLI Usage

```bash
# Analyze a single package
python main.py analyze --repo-root /path/to/kubernetes --pkg-dir pkg/client --output output/graph.json

# Analyze full repository
python main.py analyze --repo-root /path/to/kubernetes --output output/code-graph-full.json

# Find callers of a function
python main.py find-callers --graph output/code-graph-full.json --function NewClient

# Graph statistics
python main.py analyze-graph --graph output/code-graph-full.json --top-n 30
```

## Project Structure

```
code-graph-builder/
├── src/
│   ├── chatbot_service.py     # FastAPI app — streaming chat, tool execution, auth
│   ├── api_service.py         # REST API for graph queries
│   ├── file_index.py          # SQLite FTS5 index over Go source files
│   ├── doc_index.py           # SQLite FTS5 index over K8s documentation
│   ├── parser/                # tree-sitter Go parser + AST visitor
│   ├── graph/                 # CodeGraph data model (FunctionNode, TypeNode, CallEdge)
│   └── query/                 # Query engine (callers, callees, call chains, critical funcs)
├── static/index.html          # Browser chat UI with markdown rendering
├── frontend/                  # React chat app (alternative UI)
├── deploy/
│   ├── k8s-manifests.yaml     # Namespace, ServiceAccount, Deployment, Service
│   └── deploy.ps1             # Deployment helper
├── terraform/                 # Azure IaC (AKS, ACR, OpenAI, managed identity)
├── scripts/
│   ├── rebuild.ps1            # End-to-end: ACR build → AKS deploy
│   ├── teardown.ps1           # terraform destroy wrapper
│   └── setup-minikube.ps1     # Local Minikube setup
├── main.py                    # CLI (analyze, find-callers, analyze-graph)
├── Dockerfile                 # Multi-stage build with baked-in K8s source + indexes
├── docker-compose.yml         # Local dev: backend + React frontend
├── tests/test_tools.py        # 57 tests
└── requirements.txt
```

## LLM Tools

The chatbot exposes these tools to GPT-4o for multi-step reasoning:

| Tool | Description |
|------|-------------|
| `grep_code` | Full-text search across 11k+ Go source files |
| `read_file` | Read source file contents by path and line range |
| `find_callers` | Find all functions that call a given function |
| `search_graph` | Search the code graph for functions/types by name |
| `list_directory` | Browse the repository directory tree |
| `search_docs` | Full-text search across Kubernetes documentation |
| `read_doc` | Read a specific documentation page |

## Configuration

Copy `.env.example` to `.env` and set:

| Variable | Description |
|----------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL |
| `AZURE_DEPLOYMENT_NAME` | Deployment name (e.g., `gpt-4o`) |
| `GRAPH_PATH` | Path to code graph JSON |
| `REPO_ROOT` | Path to Kubernetes source checkout |
| `DOCS_ROOT` | Path to kubernetes.io docs content |
| `INDEX_DB` | Path to file search SQLite DB |
| `DOCS_INDEX_DB` | Path to doc search SQLite DB |

## License

Apache License 2.0
