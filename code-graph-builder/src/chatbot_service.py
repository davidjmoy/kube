"""Chatbot backend with streaming responses and tool-calling.

The LLM can grep, read files, and query the code graph autonomously.
Streams responses token-by-token via Server-Sent Events (SSE).
"""

import os
import re
import json
import time
import secrets
import logging
import subprocess
from typing import AsyncGenerator
from functools import lru_cache
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("chatbot")

from fastapi import FastAPI, HTTPException, Query, Request, Depends, status
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
import asyncio

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from openai import AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from src.graph import CodeGraphSerializer
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

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")
    if o.strip()
]

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


def _validate_config():
    """Validate required env vars at startup with clear errors."""
    errors = []
    if settings.azure_endpoint == "https://YOUR.openai.azure.com/":
        errors.append("AZURE_OPENAI_ENDPOINT is not configured (still set to placeholder)")
    if not settings.graph_path.exists():
        errors.append(f"GRAPH_PATH={settings.graph_path} does not exist -- run 'python main.py analyze' first")
    if not REPO_ROOT.exists():
        errors.append(f"REPO_ROOT={REPO_ROOT} does not exist")
    if errors:
        for e in errors:
            logger.error(f"CONFIG ERROR: {e}")
        # Don't exit — log warnings so the service can still start in degraded mode
        logger.warning(f"Startup has {len(errors)} config warning(s). Some features may not work.")


_validate_config()

# ============================================================================
# Initialize FastAPI and clients
# ============================================================================

# Documentation index
DOCS_INDEX_DB = Path(os.getenv("DOCS_INDEX_DB", "output/doc-index.db"))
doc_index = DocIndex(DOCS_INDEX_DB, DOCS_ROOT)

# Ripgrep binary (used for grep_code tool)
RIPGREP_BIN = os.getenv("RIPGREP_BIN", "rg")


@asynccontextmanager
async def lifespan(app):
    """Startup: ensure doc index exists."""
    if doc_index.exists:
        logger.info("Doc index loaded (pre-built)")
    elif DOCS_ROOT.exists():
        logger.info("Doc index not found \u2014 building \u2026")
        stats = await asyncio.to_thread(doc_index.build)
        logger.info(f"Doc index ready: {stats}")
    else:
        logger.info(f"No doc index and docs root not found ({DOCS_ROOT}), doc search disabled")

    yield
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
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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

# ---- Static files (React build) ----
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(verify_auth)])
async def root():
    """Serve the React frontend (or a helpful message if not built yet)."""
    html_path = STATIC_DIR / "index.html"
    if not html_path.exists():
        return HTMLResponse(
            content="<h1>Frontend not built</h1><p>Run <code>cd frontend && npm install && npm run build</code></p>",
            status_code=503,
        )
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

# Mount React build's asset files (JS, CSS, media)
if (STATIC_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR / "static"), name="react-assets")

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


@lru_cache(maxsize=1)
def get_symbol_suggestion_index() -> dict:
    """Build a compact in-memory index for type-ahead suggestions."""
    graph_data = get_graph_query()
    functions = graph_data.get("functions", {})
    types = graph_data.get("types", {})

    type_items = []
    for type_node in types.values():
        type_items.append({
            "kind": "class",
            "name": type_node.get("name", ""),
            "package": type_node.get("package", ""),
            "insert_text": type_node.get("name", ""),
            "location": type_node.get("location", {}),
        })

    method_items = []
    for fn in functions.values():
        if not fn.get("is_method"):
            continue
        name = fn.get("name", "")
        receiver = fn.get("receiver") or ""
        display_name = f"{receiver}.{name}" if receiver else name
        method_items.append({
            "kind": "method",
            "name": display_name,
            "method_name": name,
            "receiver": receiver,
            "package": fn.get("package", ""),
            "insert_text": display_name,
            "location": fn.get("location", {}),
        })

    return {"types": type_items, "methods": method_items}


def _suggestion_score(query: str, candidate: str) -> int:
    """Rank suggestions by best match quality (higher is better)."""
    q = query.lower()
    c = candidate.lower()

    if c == q:
        return 100
    if c.startswith(q):
        return 80
    dot_token = c.split(".")[-1]
    if dot_token.startswith(q):
        return 70
    idx = c.find(q)
    if idx >= 0:
        return max(10, 60 - idx)
    return 0


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
    },
    {
        "type": "function",
        "function": {
            "name": "find_files",
            "description": "Find files by glob pattern in the Kubernetes repo. Use this when you don't know the exact file path but know a naming pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern to match. Examples: '*_test.go', '*.yaml', 'BUILD', 'Makefile'"
                    },
                    "path": {
                        "type": "string",
                        "description": "Subdirectory to search within (relative to repo root). Default: '' (entire repo)"
                    }
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_git_history",
            "description": "Get recent git commits for a file or directory. Use this to understand recent changes, who modified code, and when.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "File or directory path relative to repo root. Example: 'pkg/kubelet/kubelet.go'"
                    },
                    "max_count": {
                        "type": "integer",
                        "description": "Maximum number of commits to return. Default: 15"
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

def _safe_resolve(base: Path, user_path: str) -> Path | None:
    """Resolve user_path under base, returning None if it escapes."""
    try:
        resolved = (base / user_path).resolve()
        if resolved.is_relative_to(base.resolve()):
            return resolved
    except (ValueError, OSError):
        pass
    return None


def execute_tool(name: str, arguments: dict) -> dict:
    """Execute a tool call and return the result with timing metadata."""
    logger.info(f"Tool call: {name}({json.dumps(arguments, ensure_ascii=False)[:200]})")
    start = time.time()
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
        elif name == "find_files":
            result = _tool_find_files(arguments)
        elif name == "get_git_history":
            result = _tool_get_git_history(arguments)
        else:
            result = f"Unknown tool: {name}"
        duration_ms = int((time.time() - start) * 1000)
        logger.info(f"Tool {name} returned {len(result)} chars in {duration_ms}ms")
        return {"result": result, "duration_ms": duration_ms, "result_chars": len(result)}
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        logger.exception(f"Tool {name} failed")
        error_msg = f"Error executing {name}: {e}"
        return {"result": error_msg, "duration_ms": duration_ms, "result_chars": len(error_msg)}


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


def _run_ripgrep(pattern: str, search_dir: Path, include: str, max_matches: int, context_lines: int = 2) -> str:
    """Run ripgrep subprocess and return formatted output."""
    args = [
        RIPGREP_BIN,
        "--no-heading",
        "--line-number",
        "--color", "never",
        "--ignore-case",
        "--max-count", "10",
        "--glob", include,
        "--glob", "!vendor/**",
        "--glob", "!third_party/**",
        "--glob", "!*_generated*",
    ]
    if context_lines:
        args.extend(["-C", str(context_lines)])
    args.extend(["--", pattern, str(search_dir)])

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(REPO_ROOT),
        )
        # rg exit code 1 = no matches (not an error)
        if result.returncode == 1:
            return ""
        if result.returncode != 0:
            logger.warning(f"ripgrep error (exit {result.returncode}): {result.stderr[:200]}")
            return ""
        # Truncate output to prevent megabytes from flooding context
        output = result.stdout
        if len(output) > 8000:
            output = output[:8000]
        return output
    except FileNotFoundError:
        logger.warning(f"ripgrep binary not found at '{RIPGREP_BIN}', falling back to Python grep")
        return ""
    except subprocess.TimeoutExpired:
        logger.warning("ripgrep timed out after 30s")
        return ""


def _tool_grep(args: dict) -> str:
    """Grep the Kubernetes source code using ripgrep, with graph-guided fallback."""
    pattern = args["pattern"]
    path = args.get("path", "pkg")
    include = args.get("include_pattern", "*.go")

    resolved = _safe_resolve(REPO_ROOT, path)
    if resolved is None:
        return "Error: path not allowed (outside repo root)"
    search_dir = resolved
    if not search_dir.exists():
        return f"Directory not found: {path}"

    MAX_MATCHES = 60
    DISPLAY = 50
    MAX_CHARS = 6000

    try:
        # --- Phase 0: ripgrep (fast, full-featured) ---
        rg_output = _run_ripgrep(pattern, search_dir, include, MAX_MATCHES)
        if rg_output:
            # Make paths relative to REPO_ROOT for cleaner output
            repo_str = str(REPO_ROOT).replace("\\", "/")
            rg_output = rg_output.replace(repo_str + "/", "").replace(repo_str, "")
            lines = rg_output.rstrip().split("\n")
            if len(lines) > DISPLAY:
                output = "\n".join(lines[:DISPLAY])
                return f"(ripgrep)\n{output}\n\n... (showing {DISPLAY} of {len(lines)} lines, narrow your search)"
            truncated = rg_output[:MAX_CHARS]
            if len(rg_output) > MAX_CHARS:
                truncated += f"\n\n... (truncated at {MAX_CHARS} chars)"
            return f"(ripgrep)\n{truncated}"

        # --- Phase 1: graph-guided Python search (fallback if rg not available) ---
        pat = re.compile(re.escape(pattern), re.IGNORECASE)
        graph_files = _graph_files_for_pattern(pattern, path)
        if graph_files:
            logger.info(f"Graph narrowed grep to {len(graph_files)} files")
            resolved = [REPO_ROOT / f for f in graph_files if (REPO_ROOT / f).is_file()]
            matches = []
            for go_file in resolved:
                rel = str(go_file.relative_to(REPO_ROOT)).replace("\\", "/")
                try:
                    with open(go_file, "r", encoding="utf-8", errors="ignore") as f:
                        for line_no, line in enumerate(f, 1):
                            if pat.search(line):
                                matches.append(f"{rel}:{line_no}: {line.rstrip()}")
                                if len(matches) >= MAX_MATCHES:
                                    break
                except (OSError, PermissionError):
                    continue
                if len(matches) >= MAX_MATCHES:
                    break
            if matches:
                if len(matches) >= MAX_MATCHES:
                    return "(graph-guided search)\n" + "\n".join(matches[:DISPLAY]) + f"\n\n... (truncated at {DISPLAY} of {MAX_MATCHES}+ matches)"
                return f"(graph-guided search, {len(graph_files)} files)\n" + "\n".join(matches)

        return f"No matches found for '{pattern}' in {path}/{include}"
    except Exception as e:
        return f"Grep error: {e}"


def _tool_read_file(args: dict) -> str:
    """Read lines from a file in the repo."""
    file_path = args["file_path"]

    resolved = _safe_resolve(REPO_ROOT, file_path)
    if resolved is None:
        return "Error: path not allowed (outside repo root)"
    if not resolved.exists():
        return f"File not found: {file_path}"
    if not resolved.is_file():
        return f"Not a file: {file_path}"

    start = args.get("start_line", 1)
    end = args.get("end_line", start + 100)

    # Cap read window to 200 lines to avoid flooding context
    MAX_READ_LINES = 200
    if end - start > MAX_READ_LINES:
        end = start + MAX_READ_LINES

    try:
        with open(resolved, "r", encoding="utf-8", errors="ignore") as f:
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

    if rel_path:
        resolved = _safe_resolve(REPO_ROOT, rel_path)
        if resolved is None:
            return "Error: path not allowed (outside repo root)"
        dir_path = resolved
    else:
        dir_path = REPO_ROOT

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

    if DOCS_ROOT.exists() and _safe_resolve(DOCS_ROOT, file_path) is None:
        return "Error: path not allowed (outside docs root)"

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


def _tool_find_files(args: dict) -> str:
    """Find files matching a glob pattern in the repo."""
    pattern = args["pattern"]
    path = args.get("path", "")
    if path:
        resolved = _safe_resolve(REPO_ROOT, path)
        if resolved is None:
            return "Error: path not allowed (outside repo root)"
        search_dir = resolved
    else:
        search_dir = REPO_ROOT

    if not search_dir.exists():
        return f"Directory not found: {path}"

    MAX_RESULTS = 50
    matches = []
    for f in search_dir.rglob(pattern):
        rel = str(f.relative_to(REPO_ROOT)).replace("\\", "/")
        if any(skip in rel.lower() for skip in ["vendor/", "third_party/", "_generated", "node_modules/"]):
            continue
        matches.append(rel)
        if len(matches) >= MAX_RESULTS:
            break

    if not matches:
        return f"No files matching '{pattern}' in {path or '/'}"
    result = f"Found {len(matches)} file(s) matching '{pattern}':\n"
    result += "\n".join(f"  {m}" for m in sorted(matches))
    if len(matches) >= MAX_RESULTS:
        result += f"\n\n... (truncated at {MAX_RESULTS}, narrow your search)"
    return result


def _tool_get_git_history(args: dict) -> str:
    """Get recent git commits for a file or directory."""
    file_path = args["file_path"]
    max_count = min(args.get("max_count", 15), 30)

    resolved = _safe_resolve(REPO_ROOT, file_path)
    if resolved is None:
        return "Error: path not allowed (outside repo root)"
    if not resolved.exists():
        return f"Path not found: {file_path}"

    try:
        rel_path = str(resolved.relative_to(REPO_ROOT.resolve())).replace("\\", "/")
        result = subprocess.run(
            ["git", "log", f"--oneline", f"-n{max_count}", "--", rel_path],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return f"Git error: {result.stderr.strip()}"
        output = result.stdout.strip()
        if not output:
            return f"No git history found for '{file_path}'"
        return f"Recent commits for {file_path}:\n{output}"
    except subprocess.TimeoutExpired:
        return "Git log timed out (15s limit)"
    except FileNotFoundError:
        return "Git is not installed or not in PATH"


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
- find_files: Find files by glob pattern (e.g. '*_test.go', 'Makefile')
- get_git_history: See recent commits for a file or directory

**Documentation Tools:**
- search_docs: Search the official Kubernetes docs by topic
- read_doc: Read the full content of a documentation page

**When to use which:**
- For "how does X work internally" or "show me the implementation" → use code tools
- For "how do I configure X" or "what is the concept of X" → use doc tools
- For architecture questions → use both: docs for overview, code for details

**Strategy:**
1. Search first (grep_code or search_graph), then read the results (read_file)
2. Use find_files when you don't know the exact path but know a naming pattern
3. Use get_git_history to understand recent changes to a file
4. Follow dependency chains: find_callers → read_file on callers → repeat
5. Don't stop at the first result — check negatives and verify assumptions

**Response format:**
- Start with a brief answer (TL;DR)
- Then provide details with code references
- End with "Watch out for" notes if relevant

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
# Input validation
# ============================================================================

MAX_MESSAGE_LENGTH = 10_000
MAX_HISTORY_MESSAGES = 20
MAX_HISTORY_MSG_LENGTH = 5_000


def _sanitize_request(request: ChatRequest) -> ChatRequest:
    """Truncate history and validate message length."""
    # Truncate history to last N messages
    if len(request.conversation_history) > MAX_HISTORY_MESSAGES:
        request.conversation_history = request.conversation_history[-MAX_HISTORY_MESSAGES:]
    # Truncate individual history messages
    for msg in request.conversation_history:
        if len(msg.content) > MAX_HISTORY_MSG_LENGTH:
            msg.content = msg.content[:MAX_HISTORY_MSG_LENGTH] + "\n... (truncated)"
    return request


# ============================================================================
# Streaming Chat Endpoint
# ============================================================================

def _tool_description(name: str, args: dict) -> str:
    """Build a human-readable summary of a tool call."""
    if name == "grep_code":
        return f"Searching for '{args.get('pattern', '')}'"
    elif name == "read_file":
        return f"Reading {args.get('file_path', '')}"
    elif name == "find_callers":
        return f"Finding callers of {args.get('function_name', '')}"
    elif name == "search_graph":
        return f"Searching graph for '{args.get('query', '')}'"
    elif name == "list_directory":
        return f"Listing {args.get('path', '/')}"
    elif name == "search_docs":
        return f"Searching docs for '{args.get('query', '')}'"
    elif name == "read_doc":
        return f"Reading doc: {args.get('file_path', '')}"
    elif name == "find_files":
        return f"Finding files matching '{args.get('pattern', '')}'"
    elif name == "get_git_history":
        return f"Git history for {args.get('file_path', '')}"
    return name


async def generate_streaming_response(request: ChatRequest) -> AsyncGenerator[str, None]:
    """Generate streaming chat response with tool-calling loop."""

    try:
        # Validate message length
        if len(request.message) > MAX_MESSAGE_LENGTH:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Message too long ({len(request.message)} chars). Maximum is {MAX_MESSAGE_LENGTH}.'})}\n\n"
            return

        request = _sanitize_request(request)

        # Build messages
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        for msg in request.conversation_history:
            messages.append({"role": msg.role, "content": msg.content})

        messages.append({"role": "user", "content": request.message})
        logger.info(f"Chat request: {request.message[:100]}")

        max_tool_rounds = 8
        tool_round = 0
        all_steps = []
        loop_start = time.time()

        while tool_round < max_tool_rounds:
            tool_round += 1
            logger.info(f"LLM call round {tool_round}")

            # First, make a non-streaming call to check for tool calls
            # (streaming + tool_calls don't mix well with Azure OpenAI)
            response = await async_client.chat.completions.create(
                model=settings.deployment_name,
                messages=messages,
                tools=TOOLS,
                max_tokens=settings.max_tokens,
                temperature=0.3,
            )

            if not response.choices:
                yield f"data: {json.dumps({'type': 'error', 'message': 'No response from LLM (possibly content filter)'})}\n\n"
                return

            choice = response.choices[0]

            # If the model wants to call tools, execute them
            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                # Add the assistant message with tool calls
                messages.append(choice.message)

                # Execute each tool call with structured events
                for tool_call in choice.message.tool_calls:
                    fn_name = tool_call.function.name
                    try:
                        fn_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        fn_args = {}
                        logger.warning(f"Bad JSON from LLM for tool {fn_name}: {tool_call.function.arguments[:100]}")
                    desc = _tool_description(fn_name, fn_args)

                    # Emit tool_start
                    yield f"data: {json.dumps({'type': 'tool_start', 'name': fn_name, 'args_summary': desc, 'round': tool_round})}\n\n"

                    # Run tool in thread to avoid blocking the event loop
                    ret = await asyncio.to_thread(execute_tool, fn_name, fn_args)

                    # Emit tool_end
                    yield f"data: {json.dumps({'type': 'tool_end', 'name': fn_name, 'duration_ms': ret['duration_ms'], 'result_chars': ret['result_chars'], 'round': tool_round})}\n\n"

                    all_steps.append({
                        "name": fn_name,
                        "args_summary": desc,
                        "duration_ms": ret["duration_ms"],
                        "result_chars": ret["result_chars"],
                        "round": tool_round,
                        "status": "success" if not ret["result"].startswith("Error") else "error",
                    })

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": ret["result"]
                    })

                continue

            # No tool calls — stream the final answer token-by-token
            final_text = choice.message.content or ""

            # Re-call with stream=True for genuine token-by-token delivery
            stream_response = await async_client.chat.completions.create(
                model=settings.deployment_name,
                messages=messages,
                max_tokens=settings.max_tokens,
                temperature=0.3,
                stream=True,
            )
            async for chunk in stream_response:
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    yield f"data: {json.dumps({'token': token})}\n\n"

            break

        # Emit execution trace summary
        total_duration_ms = int((time.time() - loop_start) * 1000)
        if all_steps:
            trace = {
                "type": "trace",
                "rounds": tool_round,
                "total_duration_ms": total_duration_ms,
                "total_tool_calls": len(all_steps),
                "steps": all_steps,
            }
            yield f"data: {json.dumps(trace)}\n\n"

        yield "data: {\"type\": \"complete\"}\n\n"

    except Exception as e:
        error_msg = {"type": "error", "message": str(e)}
        yield f"data: {json.dumps(error_msg)}\n\n"


@app.post("/chat/stream", dependencies=[Depends(verify_auth)])
@limiter.limit("20/minute")
async def chat_stream(request: Request, chat_request: ChatRequest):
    """Stream chat response with code context.

    Streams tokens one at a time via Server-Sent Events.

    Example response:
    data: {"token": "The"}
    data: {"token": " Kubernetes"}
    data: {"references": [...]}
    data: {"type": "complete"}
    """
    return StreamingResponse(
        generate_streaming_response(chat_request),
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
@limiter.limit("20/minute")
async def chat(request: Request, chat_request: ChatRequest):
    """Non-streaming chat endpoint with tool-calling."""

    if len(chat_request.message) > MAX_MESSAGE_LENGTH:
        raise HTTPException(status_code=400, detail=f"Message too long ({len(chat_request.message)} chars). Maximum is {MAX_MESSAGE_LENGTH}.")

    chat_request = _sanitize_request(chat_request)

    try:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in chat_request.conversation_history:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": chat_request.message})

        max_rounds = 8
        for _ in range(max_rounds):
            response = await async_client.chat.completions.create(
                model=settings.deployment_name,
                messages=messages,
                tools=TOOLS,
                max_tokens=settings.max_tokens,
                temperature=0.3,
            )

            if not response.choices:
                raise HTTPException(status_code=502, detail="No response from LLM (possibly content filter)")

            choice = response.choices[0]
            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                messages.append(choice.message)
                for tool_call in choice.message.tool_calls:
                    fn_name = tool_call.function.name
                    try:
                        fn_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        fn_args = {}
                    ret = await asyncio.to_thread(execute_tool, fn_name, fn_args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": ret["result"]
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


@app.get("/graph/suggest", dependencies=[Depends(verify_auth)])
async def graph_suggest(
    q: str = Query(..., min_length=1, max_length=120),
    limit: int = Query(10, ge=1, le=25),
):
    """Type-ahead suggestions for class/type and method names."""
    try:
        query = q.strip()
        if not query:
            return {"query": q, "results": []}

        index = get_symbol_suggestion_index()
        candidates = index["types"] + index["methods"]

        seen = set()
        scored = []
        for item in candidates:
            score = _suggestion_score(query, item.get("name", ""))
            if score <= 0:
                continue
            key = (item.get("kind"), item.get("name"), item.get("package"))
            if key in seen:
                continue
            seen.add(key)
            scored.append((score, item))

        scored.sort(key=lambda pair: (-pair[0], pair[1].get("name", "").lower()))

        results = []
        for score, item in scored[:limit]:
            results.append({
                "kind": item["kind"],
                "name": item["name"],
                "package": item.get("package", ""),
                "insert_text": item.get("insert_text", item["name"]),
                "location": item.get("location", {}),
                "score": score,
            })

        return {"query": query, "results": results}
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
