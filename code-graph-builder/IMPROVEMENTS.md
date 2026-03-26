# Improvements Roadmap

Analysis of the code-graph-builder project as of March 2026. Organized by priority, with concrete locations and fixes.

---

## P0 — Security

### Hardcoded secrets in source control
- `terraform/variables.tf` — subscription ID `15115821-...` baked into defaults
- ~~`scripts/rebuild.ps1` — default auth credentials removed; now reads from `.env`~~
- `deploy/k8s-manifests.yaml`, `k8s-aks.yaml` — Azure OpenAI endpoint and static IP hardcoded

**Fix:** Move secrets to Azure Key Vault or `.env` files. Use Terraform variables with no defaults for sensitive values. Parameterize K8s manifests (Kustomize or Helm).

### Open CORS
- `src/chatbot_service.py` and `src/api_service.py` both set `allow_origins=["*"]`
- Any domain can call authenticated endpoints, bypassing same-origin protections

**Fix:** Whitelist specific origins via env var (e.g., `ALLOWED_ORIGINS`).

### No rate limiting
- No throttle on `/chat/stream` or any other endpoint
- Azure OpenAI token costs are unbounded under abuse

**Fix:** Add `slowapi` middleware or front with Azure Application Gateway.

### No HTTPS enforcement
- All examples and health checks use HTTP
- Basic auth credentials sent in plaintext without TLS

**Fix:** Add TLS termination via Ingress controller or Azure Application Gateway. Redirect HTTP→HTTPS.

### Incomplete path traversal protection
- `chatbot_service.py` blocks `".."` in paths but doesn't resolve symlinks
- A symlink inside the repo could escape the repo root

**Fix:** Use `Path.resolve()` then verify `resolved.is_relative_to(repo_root)`.

---

## P1 — Performance

### Full graph loaded in memory
- `chatbot_service.py` loads the entire 97 MB JSON graph into a Python dict on startup
- High memory footprint; slow startup; every query scans the full dict

**Fix:** Store graph in SQLite. Query only needed nodes. Expect ~90% memory reduction.

### Blocking I/O in async context
- `file_index.py` `build()` and `doc_index.py` `build()` read thousands of files synchronously
- Called from FastAPI async lifespan, blocking the event loop for 20–60 seconds

**Fix:** Wrap in `asyncio.to_thread()` or `run_in_executor`.

### No incremental parsing
- `go_parser.py` re-parses every file from scratch on every run
- Full Kubernetes analysis takes 5–10 minutes

**Fix:** Cache file mtimes. Only re-parse changed files. Merge results into existing graph.

### FTS index limited to Go files
- `chatbot_service.py` only uses FTS for `*.go` files; YAML, Markdown, etc. fall back to `rglob` full scan

**Fix:** Extend `file_index.py` to index all source file types.

### No query caching
- `api_service.py` `/functions/search` does an O(n) scan of all functions on every request

**Fix:** Add LRU cache for frequent queries or move to SQLite with indexes.

---

## P1 — Code Quality

### Cross-package call resolution missing
- `ast_visitor.py` generates callee IDs as `file:package:name` assuming same-package calls
- When `pkg/a` calls an exported function in `pkg/b`, the ID is wrong
- `find_callers` returns incomplete results for exported functions

**Fix:** Track import declarations. Resolve call targets across packages using import→package mapping.

### Silent parse failures
- `go_parser.py` catches `Exception`, prints to stdout, returns `False`
- Users don't know the graph is incomplete

**Fix:** Use proper logging with severity. Surface error counts in graph stats.

### Generic exception handling in streaming
- `chatbot_service.py` SSE streaming catches bare `Exception` — no distinction between user error vs. system error
- Client can't tell if retrying will help

**Fix:** Catch specific exceptions. Return structured error types (e.g., `auth_error`, `llm_error`, `tool_error`).

### Invalid fallback objects
- `graph_query.py` creates dummy `FunctionNode` with `location=None` as a filter fallback
- If serialized, this crashes

**Fix:** Filter with a proper predicate instead of constructing invalid sentinel objects.

---

## P2 — Test Coverage

### No parser tests
- `src/parser/` has zero test coverage
- Function extraction, method receiver parsing, call edge creation — all untested
- Regex patterns like `r'\*?\s*([A-Za-z_]\w*)'` have no edge-case tests

**Fix:** Create `tests/test_parser.py` with known Go source snippets and expected outputs.

### No graph operation tests
- `src/graph/` has no dedicated tests
- Bidirectional reference integrity (A calls B → B.callers includes A) is unverified
- Serialization/deserialization round-trip untested

**Fix:** Create `tests/test_graph.py`.

### Tool tests require full repo
- `tests/test_tools.py` skips most tests if the Kubernetes repo or indexes aren't present
- Can't run in CI

**Fix:** Add mock-based tests that use small sample data. Keep integration tests as optional.

### No integration tests
- No end-to-end test: parse → build graph → query → serve → chat
- No API endpoint tests

**Fix:** Create `tests/test_integration.py` with a small Go module as fixture.

---

## P2 — Stale / Duplicate Code

### Redundant K8s manifests
- `deploy/k8s-manifests.yaml` — current AKS deployment
- `k8s-aks.yaml` — older AKS manifest (different image tags, env vars)
- `k8s-deployment.yaml` — Job template
- `k8s-minikube.yaml` — local dev

Four manifests with overlapping purpose and divergent config.

**Fix:** Adopt Kustomize with a base + overlays for AKS / Minikube. Remove `k8s-aks.yaml` and `k8s-deployment.yaml`.

### Two API services
- `api_service.py` — standalone REST API for graph queries
- `chatbot_service.py` — full chatbot that duplicates the same graph endpoints

**Fix:** Remove `api_service.py` or import its routes into the chatbot service.

### Two frontend implementations
- `static/index.html` — served by FastAPI, actually used
- `frontend/` — React app, never built or deployed

**Fix:** Pick one. If keeping the simple HTML UI, remove the React project.

### Incomplete test-workflow.py
- `test-workflow.py` ends mid-function in `phase1_cli_testing()`
- Phases 2 and 3 never implemented

**Fix:** Complete or remove.

### Orphaned files
- `check_coverage.py`, `examples.py`, `setup.sh` — unclear if still relevant
- `k8s-deployment.yaml` — a Job template that doesn't match current deployment pattern

**Fix:** Audit each; remove or document purpose.

---

## P2 — Frontend / UX

### Basic markdown rendering
- `static/index.html` uses regex-based markdown conversion
- No syntax highlighting, no table support, breaks on nested code blocks

**Fix:** Use a library like `markdown-it` or `marked.js` with syntax highlighting (Prism.js).

### Tool execution not visible
- During tool calls, user only sees a brief status message
- No intermediate results, progress feels opaque

**Fix:** Stream tool names, arguments, and abbreviated results as collapsible sections in the UI.

### No error recovery
- JavaScript `throw new Error(data.message)` on SSE error kills the chat session
- No retry button

**Fix:** Show error inline in the message stream. Offer a "Retry" action.

### No conversation persistence
- Chat history is lost on page reload

**Fix:** Save to `localStorage`. Add export-to-JSON and clear-history buttons.

---

## P3 — Infrastructure

### No auto-scaling
- `terraform/main.tf` sets `node_count = 3` with no autoscaler
- Can't handle traffic spikes; wastes money at idle

**Fix:** Add `auto_scaling_enabled = true` with `min_count`/`max_count` on the node pool.

### No monitoring or alerting
- No Prometheus metrics, no Application Insights, no dashboards
- Can't diagnose production issues; no alerts on error spikes

**Fix:** Add `/metrics` endpoint (Prometheus format). Wire up Azure Monitor or Grafana.

### No CI/CD
- Deployment is manual `scripts/rebuild.ps1`
- No automated test run on push

**Fix:** Add GitHub Actions workflow: lint → test → build image → deploy.

### No network policies
- Any pod in the AKS cluster can reach the chatbot
- No egress restrictions

**Fix:** Add Kubernetes `NetworkPolicy` restricting ingress to the load balancer and egress to Azure OpenAI.

### Health check too shallow
- `/health` only checks if the graph file loaded
- Doesn't verify Azure OpenAI connectivity or database access

**Fix:** Add deep health check that pings LLM and verifies DB connection.

### No backup for expensive indexes
- Code graph, file index, and doc index take hours to rebuild
- No persistence beyond the container filesystem

**Fix:** Use PersistentVolumeClaims or back up to Azure Blob Storage.

---

## Quick Wins

| Change | Effort | Impact |
|--------|--------|--------|
| Restrict CORS origins via env var | 5 min | Closes open CORS |
| Add `max_length` to query params | 5 min | Prevents oversized inputs |
| Wrap index builds in `asyncio.to_thread` | 15 min | Unblocks event loop during build |
| Add request ID to log lines | 15 min | Enables request tracing |
| Validate env vars on startup with clear errors | 20 min | Catches misconfig before first request |
| Remove `k8s-aks.yaml` and `k8s-deployment.yaml` | 5 min | Reduces confusion |
| Add `.env.example` entries for new vars | 10 min | Onboarding clarity |
| Switch graph to SQLite storage | 2–4 hrs | Major memory and query-speed gain |
