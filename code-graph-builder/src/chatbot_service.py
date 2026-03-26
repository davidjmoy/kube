"""Chatbot backend with streaming responses and tool-calling.

The LLM can grep, read files, and query the code graph autonomously.
Streams responses token-by-token via Server-Sent Events (SSE).
"""

import os
import re
import json
import secrets
import subprocess
import logging
from typing import AsyncGenerator, Optional
from functools import lru_cache
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("chatbot")

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Depends, status
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
import asyncio

from openai import AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from src.graph import CodeGraphSerializer
from src.query import GraphQuery
from src.file_index import FileIndex
from src.doc_index import DocIndex
from pathlib import Path


# ============================================================================
# Configuration
# ============================================================================

REPO_ROOT = Path(os.getenv("REPO_ROOT", r"c:\Users\david\repos\kubernetes"))
DOCS_ROOT = Path(os.getenv("DOCS_ROOT", r"c:\Users\david\repos\website\content\en\docs"))
GITHUB_REPO_URL = os.getenv("GITHUB_REPO_URL", "https://github.com/kubernetes/kubernetes")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "master")
DOCS_BASE_URL = os.getenv("DOCS_BASE_URL", "https://kubernetes.io")

class Settings:
    """App settings from environment variables."""
    
    def __init__(self):
        # Azure OpenAI
        self.azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "https://YOUR.openai.azure.com/")
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
        self.deployment_name = os.getenv("AZURE_DEPLOYMENT_NAME", "gpt-4o")
        
        # Code graph
        self.graph_path = Path(os.getenv("GRAPH_PATH", "output/code-graph.json"))
        
        # API settings
        self.max_context_items = int(os.getenv("MAX_CONTEXT_ITEMS", "10"))
        self.max_tokens = int(os.getenv("MAX_TOKENS", "4000"))


settings = Settings()

# ============================================================================
# Initialize FastAPI and clients
# ============================================================================

# File-content index (SQLite FTS5) — created before app so lifespan can use it
INDEX_DB = Path(os.getenv("INDEX_DB", "output/file-index.db"))
file_index = FileIndex(INDEX_DB, REPO_ROOT)

# Documentation index
DOCS_INDEX_DB = Path(os.getenv("DOCS_INDEX_DB", "output/doc-index.db"))
doc_index = DocIndex(DOCS_INDEX_DB, DOCS_ROOT)


@asynccontextmanager
async def lifespan(app):
    """Startup: ensure file-content and doc indexes exist."""
    if not file_index.exists:
        logger.info("File-content index not found \u2014 building (~20-60s) \u2026")
        stats = file_index.build()
        logger.info(f"Index ready: {stats}")
    else:
        logger.info("File-content index loaded")

    if doc_index.exists:
        logger.info("Doc index loaded (pre-built)")
    elif DOCS_ROOT.exists():
        logger.info("Doc index not found \u2014 building \u2026")
        stats = doc_index.build()
        logger.info(f"Doc index ready: {stats}")
    else:
        logger.info(f"No doc index and docs root not found ({DOCS_ROOT}), doc search disabled")

    yield
    file_index.close()
    doc_index.close()


app = FastAPI(
    title="Kubernetes Code Graph Chatbot",
    description="Ask questions about Kubernetes source code with streaming responses",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Basic Auth ----
_AUTH_USER = os.getenv("AUTH_USERNAME", "")
_AUTH_PASS = os.getenv("AUTH_PASSWORD", "")
security = HTTPBasic(auto_error=False)


def verify_auth(credentials: HTTPBasicCredentials = Depends(security)):
    """Enforce HTTP Basic Auth when AUTH_USERNAME is set."""
    if not _AUTH_USER:
        return  # auth disabled
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )
    user_ok = secrets.compare_digest(credentials.username, _AUTH_USER)
    pass_ok = secrets.compare_digest(credentials.password, _AUTH_PASS)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

# Serve the chat UI at root
@app.get("/", response_class=HTMLResponse, dependencies=[Depends(verify_auth)])
async def root():
    html_path = Path(__file__).resolve().parent.parent / "static" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

# Initialize Azure OpenAI with DefaultAzureCredential (uses az login)
credential = DefaultAzureCredential()
token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")

async_client = AsyncAzureOpenAI(
    azure_ad_token_provider=token_provider,
    api_version=settings.api_version,
    azure_endpoint=settings.azure_endpoint,
)

# ============================================================================
# Code graph management
# ============================================================================

@lru_cache(maxsize=1)
def get_graph_query():
    """Load and cache the code graph."""
    if not settings.graph_path.exists():
        raise RuntimeError(f"Graph not found: {settings.graph_path}")
    
    graph_data = CodeGraphSerializer.load_graph(settings.graph_path)
    return graph_data


@app.post("/index/rebuild", dependencies=[Depends(verify_auth)])
async def rebuild_index():
    """Force-rebuild the file-content index."""
    stats = file_index.build()
    return {"status": "rebuilt", **stats}


# ============================================================================
# Request/Response Models
# ============================================================================

class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    conversation_history: list[ChatMessage] = []
    include_graph_context: bool = True


# ============================================================================
# Tool definitions for the LLM
# ============================================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "grep_code",
            "description": "Search the Kubernetes source code for a pattern. Automatically uses the code graph to narrow to relevant files first, then falls back to full scan. Returns matching lines with file paths and line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "The search pattern (case-insensitive text or regex). Examples: 'func NewClient', 'type PodSpec struct', 'ValidateObjectMeta'"
                    },
                    "path": {
                        "type": "string",
                        "description": "Subdirectory to search within (relative to repo root). Examples: 'pkg/kubelet', 'cmd/kube-apiserver', 'staging/src/k8s.io/client-go'. Default: 'pkg'"
                    },
                    "include_pattern": {
                        "type": "string",
                        "description": "File glob to filter. Default: '*.go'. Use '*.go' for Go files, '*.yaml' for configs."
                    }
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a specific range of lines from a file in the Kubernetes repo. Use this to see the actual implementation of a function, type, or section of code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path relative to the repo root. Example: 'pkg/kubelet/kubelet.go'"
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "First line to read (1-based). Default: 1"
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Last line to read (1-based). Default: start_line + 100"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_callers",
            "description": "Find all callers of a function using the code graph. Returns which functions call the target and where they are located.",
            "parameters": {
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string",
                        "description": "Function name to find callers for. Can be partial — will match any function containing this string."
                    }
                },
                "required": ["function_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_graph",
            "description": "Search the code graph for functions, showing their callers, callees, and location. Good for understanding call chains and dependencies.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term to match against function names and packages."
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max results to return. Default: 10"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and subdirectories in a directory within the Kubernetes repo. Use this to explore the project structure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path relative to repo root. Example: 'pkg/kubelet', 'cmd'. Default: '' (repo root)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_docs",
            "description": "Search the official Kubernetes documentation for a topic. Returns matching doc pages with titles, URLs, and relevant snippets. Use this for conceptual questions, best practices, configuration guides, and 'how to' questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search terms. Examples: 'pod lifecycle', 'network policy', 'horizontal pod autoscaler', 'RBAC'"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max results to return. Default: 8"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_doc",
            "description": "Read the full content of a Kubernetes documentation page. Use after search_docs to read a specific doc in full.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Doc file path as returned by search_docs. Example: 'concepts/workloads/pods/pod-lifecycle.md'"
                    }
                },
                "required": ["file_path"]
            }
        }
    }
]


# ============================================================================
# Tool execution
# ============================================================================

def execute_tool(name: str, arguments: dict) -> str:
    """Execute a tool call and return the result as a string."""
    logger.info(f"Tool call: {name}({json.dumps(arguments, ensure_ascii=False)[:200]})")
    try:
        if name == "grep_code":
            result = _tool_grep(arguments)
        elif name == "read_file":
            result = _tool_read_file(arguments)
        elif name == "find_callers":
            result = _tool_find_callers(arguments)
        elif name == "search_graph":
            result = _tool_search_graph(arguments)
        elif name == "list_directory":
            result = _tool_list_directory(arguments)
        elif name == "search_docs":
            result = _tool_search_docs(arguments)
        elif name == "read_doc":
            result = _tool_read_doc(arguments)
        else:
            result = f"Unknown tool: {name}"
        logger.info(f"Tool {name} returned {len(result)} chars")
        return result
    except Exception as e:
        logger.exception(f"Tool {name} failed")
        return f"Error executing {name}: {e}"


def _graph_files_for_pattern(pattern: str, path: str) -> list[str]:
    """Ask the code graph which files contain functions/types matching pattern.

    Returns a list of relative file paths (e.g. 'pkg/kubelet/kubelet.go') that
    the graph says are relevant, filtered to the requested sub-directory.
    """
    try:
        graph_data = get_graph_query()
        pat = re.compile(re.escape(pattern), re.IGNORECASE)
        files: set[str] = set()

        for func in graph_data.get("functions", {}).values():
            if pat.search(func["name"]) or pat.search(func["package"]) or pat.search(func.get("doc", "")):
                files.add(func["location"]["file"])

        for typ in graph_data.get("types", {}).values():
            if pat.search(typ["name"]) or pat.search(typ["package"]):
                files.add(typ["location"]["file"])

        # Keep only files under the requested path prefix
        prefix = path.replace("\\", "/").rstrip("/") + "/"
        return sorted(f for f in files if f.startswith(prefix))
    except Exception:
        return []


def _grep_files(file_paths: list[Path], pat: re.Pattern, limit: int) -> list[str]:
    """Grep a specific set of files, returning up to *limit* matches."""
    matches: list[str] = []
    for go_file in file_paths:
        rel = str(go_file.relative_to(REPO_ROOT)).replace("\\", "/")
        try:
            with open(go_file, "r", encoding="utf-8", errors="ignore") as f:
                for line_no, line in enumerate(f, 1):
                    if pat.search(line):
                        matches.append(f"{rel}:{line_no}: {line.rstrip()}")
                        if len(matches) >= limit:
                            return matches
        except (OSError, PermissionError):
            continue
    return matches


def _tool_grep(args: dict) -> str:
    """Grep the Kubernetes source code, using the code graph to narrow files first."""
    pattern = args["pattern"]
    path = args.get("path", "pkg")
    include = args.get("include_pattern", "*.go")

    search_dir = REPO_ROOT / path
    if not search_dir.exists():
        return f"Directory not found: {path}"

    MAX_MATCHES = 60
    DISPLAY = 50
    pat = re.compile(re.escape(pattern), re.IGNORECASE)

    try:
        # --- Phase 0: FTS index lookup (sub-millisecond) ---
        if file_index.exists and include == "*.go":
            path_prefix = path.replace("\\", "/").rstrip("/") + "/"
            rows = file_index.search(pattern, path_prefix=path_prefix, limit=MAX_MATCHES)
            if rows:
                logger.info(f"FTS index returned {len(rows)} matches")
                matches = [f"{r[0]}:{r[1]}: {r[2]}" for r in rows]
                if len(matches) >= MAX_MATCHES:
                    return (
                        "(indexed search)\n"
                        + "\n".join(matches[:DISPLAY])
                        + f"\n\n... (truncated at {DISPLAY} of {MAX_MATCHES}+ matches)"
                    )
                return f"(indexed search)\n" + "\n".join(matches)

        # --- Phase 1: graph-guided search (fast, targeted) ---
        graph_files = _graph_files_for_pattern(pattern, path)
        if graph_files:
            logger.info(f"Graph narrowed grep to {len(graph_files)} files")
            resolved = [REPO_ROOT / f for f in graph_files if (REPO_ROOT / f).is_file()]
            matches = _grep_files(resolved, pat, MAX_MATCHES)
            if matches:
                if len(matches) >= MAX_MATCHES:
                    return (
                        "(graph-guided search)\n"
                        + "\n".join(matches[:DISPLAY])
                        + f"\n\n... (truncated at {DISPLAY} of {MAX_MATCHES}+ matches)"
                    )
                return f"(graph-guided search, {len(graph_files)} files)\n" + "\n".join(matches)

        # --- Phase 2: fallback file scan (bounded) ---
        logger.info(f"No index/graph hits, falling back to rglob in {path}")
        all_files: list[Path] = []
        for go_file in search_dir.rglob(include):
            rel = str(go_file.relative_to(REPO_ROOT))
            if any(skip in rel.lower() for skip in ["vendor/", "third_party/", "_generated"]):
                continue
            all_files.append(go_file)

        matches = _grep_files(all_files, pat, MAX_MATCHES)

        if not matches:
            return f"No matches found for '{pattern}' in {path}/{include}"

        if len(matches) >= MAX_MATCHES:
            return "\n".join(matches[:DISPLAY]) + f"\n\n... (truncated at {DISPLAY} of {MAX_MATCHES}+ matches, narrow your search)"
        return "\n".join(matches)
    except Exception as e:
        return f"Grep error: {e}"


def _tool_read_file(args: dict) -> str:
    """Read lines from a file in the repo."""
    file_path = args["file_path"]
    # Sanitize: no path traversal
    if ".." in file_path:
        return "Error: path traversal not allowed"

    full_path = REPO_ROOT / file_path
    if not full_path.exists():
        return f"File not found: {file_path}"
    if not full_path.is_file():
        return f"Not a file: {file_path}"

    start = args.get("start_line", 1)
    end = args.get("end_line", start + 100)

    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            all_lines = f.readlines()

        start = max(1, start)
        end = min(len(all_lines), end)
        selected = all_lines[start - 1 : end]

        header = f"// {file_path} (lines {start}-{end} of {len(all_lines)})\n"
        return header + "".join(f"{i}: {line}" for i, line in enumerate(selected, start=start))
    except Exception as e:
        return f"Error reading file: {e}"


def _tool_find_callers(args: dict) -> str:
    """Find callers using the code graph."""
    function_name = args["function_name"]
    graph_data = get_graph_query()
    functions = graph_data.get("functions", {})

    matches = [
        (fid, f) for fid, f in functions.items()
        if function_name.lower() in f["name"].lower()
    ]

    if not matches:
        return f"No function matching '{function_name}' found in the code graph."

    result_parts = []
    for fid, func in matches[:5]:
        part = f"## {func['name']} ({func['package']})\n"
        part += f"File: {func['location']['file']}:{func['location']['line']}\n"
        part += f"Signature: {func.get('signature', 'N/A')[:200]}\n"

        callers = func.get("callers", [])
        if callers:
            part += f"Callers ({len(callers)}):\n"
            for caller_id in callers[:15]:
                caller = functions.get(caller_id)
                if caller:
                    part += f"  - {caller['name']} ({caller['package']}) at {caller['location']['file']}:{caller['location']['line']}\n"
                else:
                    part += f"  - {caller_id}\n"
            if len(callers) > 15:
                part += f"  ... and {len(callers) - 15} more\n"
        else:
            part += "No callers found in graph.\n"

        callees = func.get("callees", [])
        if callees:
            part += f"Callees ({len(callees)}):\n"
            for callee_id in callees[:10]:
                callee = functions.get(callee_id)
                if callee:
                    part += f"  - {callee['name']} ({callee['package']})\n"
                else:
                    part += f"  - {callee_id}\n"

        result_parts.append(part)

    return "\n".join(result_parts)


def _tool_search_graph(args: dict) -> str:
    """Search the code graph for functions."""
    query = args["query"].lower()
    max_results = args.get("max_results", 10)
    graph_data = get_graph_query()
    functions = graph_data.get("functions", {})

    scored = []
    for fid, func in functions.items():
        score = 0
        name_lower = func["name"].lower()
        pkg_lower = func["package"].lower()
        if query in name_lower:
            score += 10
        if query in pkg_lower:
            score += 3
        if query in func.get("doc", "").lower():
            score += 5
        if score > 0:
            scored.append((score, fid, func))

    scored.sort(key=lambda x: (-x[0], -len(x[2].get("callers", []))))

    if not scored:
        return f"No functions matching '{query}' in the code graph."

    lines = []
    for score, fid, func in scored[:max_results]:
        callers = func.get("callers", [])
        callees = func.get("callees", [])
        lines.append(
            f"- {func['name']} ({func['package']}) "
            f"at {func['location']['file']}:{func['location']['line']} "
            f"[{len(callers)} callers, {len(callees)} callees]"
        )

    return f"Found {len(scored)} matches (showing top {min(max_results, len(scored))}):\n" + "\n".join(lines)


def _tool_list_directory(args: dict) -> str:
    """List directory contents in the repo."""
    rel_path = args.get("path", "")
    if ".." in rel_path:
        return "Error: path traversal not allowed"

    dir_path = REPO_ROOT / rel_path if rel_path else REPO_ROOT
    if not dir_path.exists():
        return f"Directory not found: {rel_path}"

    entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
    lines = []
    for entry in entries[:80]:
        if entry.name.startswith("."):
            continue
        suffix = "/" if entry.is_dir() else ""
        lines.append(f"  {entry.name}{suffix}")

    header = f"Contents of {rel_path or '/'}:\n"
    return header + "\n".join(lines)


def _github_url(file_path: str, line: int | None = None) -> str:
    """Build a GitHub URL for a source file."""
    url = f"{GITHUB_REPO_URL}/blob/{GITHUB_BRANCH}/{file_path}"
    if line:
        url += f"#L{line}"
    return url


def _tool_search_docs(args: dict) -> str:
    """Search Kubernetes documentation."""
    query = args["query"]
    max_results = args.get("max_results", 8)

    if not doc_index.exists:
        return "Documentation index not available. Only code search is available."

    results = doc_index.search(query, limit=max_results)
    if not results:
        return f"No documentation found matching '{query}'."

    lines = [f"Found {len(results)} docs matching '{query}':\n"]
    for r in results:
        url = f"{DOCS_BASE_URL}{r['url']}"
        lines.append(f"- **{r['title']}**")
        lines.append(f"  URL: {url}")
        lines.append(f"  File: {r['file']}")
        if r.get("snippet"):
            snippet = r["snippet"].replace("\n", " ")[:200]
            lines.append(f"  Snippet: {snippet}")
        lines.append("")
    return "\n".join(lines)


def _tool_read_doc(args: dict) -> str:
    """Read full content of a documentation page."""
    file_path = args["file_path"]
    if ".." in file_path:
        return "Error: path traversal not allowed"

    if not doc_index.exists:
        return "Documentation index not available."

    doc = doc_index.get_doc(file_path)
    if not doc:
        return f"Doc not found: {file_path}"

    url = f"{DOCS_BASE_URL}{doc['url']}"
    header = f"# {doc['title']}\nURL: {url}\n\n"
    content = doc["content"]
    # Truncate very long docs
    if len(content) > 8000:
        content = content[:8000] + "\n\n... (truncated, doc is very long)"
    return header + content


# ============================================================================
# System prompt
# ============================================================================

SYSTEM_PROMPT = f"""You are an expert Kubernetes developer with direct access to the Kubernetes source code repository AND the official Kubernetes documentation.

You have tools to search and read both source code and documentation. USE THEM. Do not guess or rely on general knowledge — look up the real code and docs.

**Source Code Tools:**
- grep_code: Search for patterns across source files (like grep)
- read_file: Read specific lines from a source file
- find_callers: Query the code graph for who calls a function
- search_graph: Search the code graph for functions by name
- list_directory: Browse the repo structure

**Documentation Tools:**
- search_docs: Search the official Kubernetes docs by topic
- read_doc: Read the full content of a documentation page

**When to use which:**
- For "how does X work internally" or "show me the implementation" → use code tools
- For "how do I configure X" or "what is the concept of X" → use doc tools
- For architecture questions → use both: docs for overview, code for details

**Workflow:**
1. Use search_graph or grep_code to find code; use search_docs for documentation
2. Use read_file to read source code, read_doc to read full docs
3. Use find_callers to trace call chains in the code graph

**Source code references:**
When citing source code, ALWAYS format file references as GitHub links:
- Single file: [{GITHUB_REPO_URL}/blob/{GITHUB_BRANCH}/path/to/file.go#L123]({GITHUB_REPO_URL}/blob/{GITHUB_BRANCH}/path/to/file.go#L123)
- Or use markdown: [`path/to/file.go:123`]({GITHUB_REPO_URL}/blob/{GITHUB_BRANCH}/path/to/file.go#L123)

**Documentation references:**
When citing docs, include the kubernetes.io URL so the user can visit it.

Never end your response with filler like "Feel free to ask!" or similar pleasantries. Just stop when done."""


# ============================================================================
# Health & Info Endpoints
# ============================================================================

@app.get("/health")
async def health():
    """Health check endpoint."""
    try:
        graph_data = get_graph_query()
        result = {
            "status": "healthy",
            "graph_loaded": True,
            "functions": len(graph_data.get("functions", {})),
            "docs_indexed": doc_index.exists,
        }
        if doc_index.exists:
            conn = doc_index._get_conn()
            row = conn.execute("SELECT COUNT(*) FROM docs").fetchone()
            result["docs_count"] = row[0] if row else 0
        return result
    except Exception as e:
        return {
            "status": "degraded",
            "error": str(e)
        }


@app.get("/info", dependencies=[Depends(verify_auth)])
async def info():
    """Get chatbot info."""
    try:
        graph_data = get_graph_query()
        metadata = graph_data.get("metadata", {})
        return {
            "model": settings.deployment_name,
            "graph_info": metadata,
            "capabilities": [
                "Code search",
                "Function call analysis",
                "Type relationships",
                "Architecture questions"
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Streaming Chat Endpoint
# ============================================================================

async def generate_streaming_response(request: ChatRequest) -> AsyncGenerator[str, None]:
    """Generate streaming chat response with tool-calling loop."""
    
    try:
        # Build messages
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        for msg in request.conversation_history:
            messages.append({"role": msg.role, "content": msg.content})
        
        messages.append({"role": "user", "content": request.message})
        logger.info(f"Chat request: {request.message[:100]}")

        max_tool_rounds = 8  # prevent infinite loops
        tool_round = 0

        while tool_round < max_tool_rounds:
            tool_round += 1
            logger.info(f"LLM call round {tool_round}")

            # Call LLM (non-streaming first to check for tool calls)
            response = await async_client.chat.completions.create(
                model=settings.deployment_name,
                messages=messages,
                tools=TOOLS,
                max_tokens=settings.max_tokens,
                temperature=0.3,
            )

            choice = response.choices[0]

            # If the model wants to call tools, execute them
            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                # Add the assistant message with tool calls
                messages.append(choice.message)

                # Tell the user which tools are being used
                for tc in choice.message.tool_calls:
                    args = json.loads(tc.function.arguments)
                    if tc.function.name == "grep_code":
                        desc = f"Searching for '{args.get('pattern', '')}'"
                    elif tc.function.name == "read_file":
                        desc = f"Reading {args.get('file_path', '')}"
                    elif tc.function.name == "find_callers":
                        desc = f"Finding callers of {args.get('function_name', '')}"
                    elif tc.function.name == "search_graph":
                        desc = f"Searching graph for '{args.get('query', '')}'"
                    elif tc.function.name == "list_directory":
                        desc = f"Listing {args.get('path', '/')}"
                    elif tc.function.name == "search_docs":
                        desc = f"Searching docs for '{args.get('query', '')}'"
                    elif tc.function.name == "read_doc":
                        desc = f"Reading doc: {args.get('file_path', '')}"
                    else:
                        desc = tc.function.name
                    status_msg = {"type": "status", "message": desc}
                    yield f"data: {json.dumps(status_msg)}\n\n"

                # Execute each tool call
                for tool_call in choice.message.tool_calls:
                    fn_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments)

                    result = execute_tool(fn_name, fn_args)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result
                    })

                # Loop back for the next LLM call
                continue

            # No tool calls — we have the final answer already
            final_text = choice.message.content or ""

            # Send it in chunks to simulate streaming
            chunk_size = 4
            for i in range(0, len(final_text), chunk_size):
                token = final_text[i : i + chunk_size]
                yield f"data: {json.dumps({'token': token})}\n\n"
                await asyncio.sleep(0.01)

            break

        yield "data: {\"type\": \"complete\"}\n\n"
        
    except Exception as e:
        error_msg = {"type": "error", "message": str(e)}
        yield f"data: {json.dumps(error_msg)}\n\n"


@app.post("/chat/stream", dependencies=[Depends(verify_auth)])
async def chat_stream(request: ChatRequest):
    """Stream chat response with code context.
    
    Streams tokens one at a time via Server-Sent Events.
    
    Example response:
    data: {"token": "The"}
    data: {"token": " Kubernetes"}
    data: {"references": [...]}
    data: {"type": "complete"}
    """
    return StreamingResponse(
        generate_streaming_response(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


# ============================================================================
# Non-streaming Chat (for comparison)
# ============================================================================

@app.post("/chat", dependencies=[Depends(verify_auth)])
async def chat(request: ChatRequest):
    """Non-streaming chat endpoint with tool-calling."""
    
    try:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in request.conversation_history:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": request.message})

        max_rounds = 8
        for _ in range(max_rounds):
            response = await async_client.chat.completions.create(
                model=settings.deployment_name,
                messages=messages,
                tools=TOOLS,
                max_tokens=settings.max_tokens,
                temperature=0.3,
            )

            choice = response.choices[0]
            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                messages.append(choice.message)
                for tool_call in choice.message.tool_calls:
                    fn_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments)
                    result = execute_tool(fn_name, fn_args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result
                    })
                continue

            return {
                "response": choice.message.content,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }

        return {"response": "Reached maximum tool rounds without a final answer.", "usage": {}}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Code Graph Endpoints (for reference)
# ============================================================================

@app.get("/graph/search", dependencies=[Depends(verify_auth)])
async def graph_search(query: str = Query(..., min_length=1)):
    """Search code graph for functions."""
    try:
        graph_data = get_graph_query()
        functions = graph_data.get("functions", {})
        
        matches = [
            (fid, f) for fid, f in functions.items()
            if query.lower() in f["name"].lower()
        ][:10]
        
        return {
            "query": query,
            "results": [
                {
                    "name": f["name"],
                    "package": f["package"],
                    "location": f["location"],
                    "callers": len(f["callers"])
                }
                for fid, f in matches
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graph/stats", dependencies=[Depends(verify_auth)])
async def graph_stats():
    """Get graph statistics."""
    try:
        graph_data = get_graph_query()
        return graph_data.get("metadata", {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
