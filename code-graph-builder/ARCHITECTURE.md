# Architecture

## System Overview

```
┌──────────────────────────────────────────────────────────────┐
│  Browser (static/index.html)                                 │
│  Markdown rendering, SSE streaming, dark theme               │
└──────────────┬───────────────────────────────────────────────┘
               │  POST /chat/stream (SSE)
               ▼
┌──────────────────────────────────────────────────────────────┐
│  FastAPI  (src/chatbot_service.py)                           │
│  HTTP Basic Auth · health check · static file serving        │
├──────────────────────────────────────────────────────────────┤
│  Azure OpenAI GPT-4o  (tool-calling loop)                    │
│  ┌────────────┬────────────┬──────────────┬────────────────┐ │
│  │ grep_code  │ read_file  │ find_callers │ search_graph   │ │
│  │ list_dir   │ search_docs│ read_doc     │                │ │
│  └─────┬──────┴─────┬──────┴──────┬───────┴───────┬────────┘ │
│        │            │             │               │          │
│        ▼            ▼             ▼               ▼          │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ ┌────────────┐  │
│  │File Index│ │Code Graph│ │  K8s Source   │ │ Doc Index  │  │
│  │(FTS5 DB) │ │  (JSON)  │ │  (on disk)   │ │ (FTS5 DB)  │  │
│  │ 549 MB   │ │  97 MB   │ │              │ │  16 MB     │  │
│  └──────────┘ └──────────┘ └──────────────┘ └────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

## Components

### Chatbot Service (`src/chatbot_service.py`)

The main application. On startup it loads three data sources:

1. **Code graph** — JSON file of 45,821 functions, 25,649 types, 119,209 call edges
2. **File index** — SQLite FTS5 database indexing every line of 11,463 Go source files
3. **Doc index** — SQLite FTS5 database indexing 1,570 Kubernetes documentation pages

Each user message triggers a tool-calling loop: GPT-4o decides which tools to call, the
service executes them, and results are fed back until the model produces a final answer.
Responses stream to the browser as Server-Sent Events.

### Code Graph (`src/graph/`, `src/parser/`, `src/query/`)

Built by `main.py analyze` using tree-sitter to parse Go source files:

- **go_parser.py** — Walks the repository, skipping vendor/test/generated files
- **ast_visitor.py** — Extracts functions, methods, types, and call expressions from the AST
- **code_graph.py** — In-memory graph with `FunctionNode`, `TypeNode`, `CallEdge`
- **graph_query.py** — Queries: callers, callees, call chains, critical functions, entry points

Symbol IDs follow the format `file:package:name` (e.g., `pkg/client/client.go:client:NewClient`).

### File Index (`src/file_index.py`)

SQLite FTS5 full-text index over Go source files, indexed line by line.
Supports prefix and quoted-phrase queries. Used by the `grep_code` tool.

### Doc Index (`src/doc_index.py`)

SQLite FTS5 full-text index over Kubernetes documentation (Hugo markdown).
Extracts Hugo frontmatter titles, strips shortcodes, converts paths to kubernetes.io URLs.
Used by the `search_docs` and `read_doc` tools.

### Browser UI (`static/index.html`)

Single-page chat interface. Renders markdown (headers, code blocks, bold, links, lists).
Connects to the backend via SSE for real-time token streaming.

## Data Flow

```
User question
    │
    ▼
chatbot_service receives POST /chat/stream
    │
    ▼
Build system prompt (inject graph summary)
    │
    ▼
Call Azure OpenAI GPT-4o with tools defined
    │
    ├─► Model returns tool_calls ──► Execute tools ──► Append results ──► Loop back
    │
    └─► Model returns content ──► Stream tokens as SSE ──► Done
```

## Infrastructure (Azure)

Managed by Terraform in `terraform/`:

| Resource | SKU / Size | Region | Monthly Cost |
|----------|-----------|--------|-------------|
| AKS cluster | 3× Standard_D4d_v4 | centralus | ~$400 |
| Azure OpenAI | S0 + per-token | centralus | varies |
| Container Registry | Basic | westus2 | ~$5 |
| Public IP | Standard static | centralus | ~$4 |
| Managed Identity | — | centralus | free |
| Resource Group | — | westus2 | free |

### Deployment Pipeline

```
terraform apply          Create Azure resources (~15 min)
        │
        ▼
scripts/rebuild.ps1      ACR build → get AKS creds → apply K8s manifests → rollout
        │
        ▼
deploy/k8s-manifests.yaml
  ├── Namespace: code-graph
  ├── ServiceAccount (workload identity)
  ├── Deployment (1 replica, 2Gi mem, 2 CPU)
  └── Service (LoadBalancer → port 80)
```

### Cost Control

```powershell
.\scripts\teardown.ps1   # terraform destroy — removes all billable resources
.\scripts\rebuild.ps1    # recreate when needed
```

## Authentication

- **Browser → Backend**: HTTP Basic Auth (username/password from K8s secret)
- **Backend → Azure OpenAI**: Azure AD workload identity (no API keys)
  - Managed identity with `Cognitive Services OpenAI User` role
  - Federated credential links K8s service account to Azure identity

## Local Development

```bash
# Bare metal
uvicorn src.chatbot_service:app --host 0.0.0.0 --port 8000 --reload

# Docker Compose (backend + React frontend)
docker-compose up

# Minikube
.\scripts\setup-minikube.ps1
```
