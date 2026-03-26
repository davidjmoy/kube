"""FastAPI backend service for code graph queries.

This service exposes the code graph through REST APIs for use by
chatbot backends, web UIs, or other client applications.

Installation:
    pip install fastapi uvicorn

Usage:
    uvicorn src.api.service:app --reload --host 0.0.0.0 --port 8000
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from pathlib import Path
import json
from datetime import datetime

from src.graph import CodeGraphSerializer, CodeGraph
from src.query import GraphQuery

# Initialize FastAPI app
app = FastAPI(
    title="Kubernetes Code Graph API",
    description="Query semantic relationships in Kubernetes source code",
    version="0.1.0"
)

# Add CORS middleware for chatbot frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global graph instance
_graph_data = None
_graph_path = Path("output/code-graph.json")


def load_graph():
    """Load graph from JSON file."""
    global _graph_data
    if _graph_data is None:
        if not _graph_path.exists():
            raise RuntimeError(f"Graph file not found: {_graph_path}")
        _graph_data = CodeGraphSerializer.load_graph(_graph_path)
    return _graph_data


# ============================================================================
# Response Models
# ============================================================================

class LocationModel(BaseModel):
    file: str
    line: int
    column: int
    end_line: int
    end_column: int


class FunctionModel(BaseModel):
    id: str
    name: str
    package: str
    location: LocationModel
    signature: str
    doc: str
    receiver: Optional[str]
    is_method: bool
    callers: List[str]
    callees: List[str]


class TypeModel(BaseModel):
    id: str
    name: str
    package: str
    location: LocationModel
    kind: str
    doc: str
    methods: List[str]


class GraphMetadataModel(BaseModel):
    repository: str
    created_at: str
    packages: List[str]
    total_functions: int
    total_types: int
    total_calls: int


# ============================================================================
# Graph Information Endpoints
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Load graph on startup."""
    try:
        load_graph()
        print("✅ Graph loaded successfully")
    except Exception as e:
        print(f"⚠️ Graph not available: {e}")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        load_graph()
        return {"status": "healthy", "graph_loaded": True}
    except Exception as e:
        return {"status": "degraded", "graph_loaded": False, "error": str(e)}


@app.get("/metadata", response_model=GraphMetadataModel)
async def get_metadata():
    """Get graph metadata."""
    graph = load_graph()
    return graph["metadata"]


@app.get("/stats")
async def get_statistics():
    """Get detailed statistics about the graph."""
    graph = load_graph()
    metadata = graph["metadata"]
    
    # Calculate additional stats
    functions = graph["functions"].values()
    types = graph["types"].values()
    
    avg_callers = sum(len(f["callers"]) for f in functions) / len(functions) if functions else 0
    avg_callees = sum(len(f["callees"]) for f in functions) / len(functions) if functions else 0
    
    # Find top 5 most-called functions
    top_called = sorted(functions, key=lambda f: len(f["callers"]), reverse=True)[:5]
    
    # Find top 5 most-calling functions
    top_callers = sorted(functions, key=lambda f: len(f["callees"]), reverse=True)[:5]
    
    return {
        "metadata": metadata,
        "statistics": {
            "average_callers_per_function": avg_callers,
            "average_callees_per_function": avg_callees,
            "most_called_functions": [
                {
                    "name": f["name"],
                    "package": f["package"],
                    "caller_count": len(f["callers"])
                }
                for f in top_called
            ],
            "most_calling_functions": [
                {
                    "name": f["name"],
                    "package": f["package"],
                    "callee_count": len(f["callees"])
                }
                for f in top_callers
            ]
        }
    }


# ============================================================================
# Function Query Endpoints
# ============================================================================

@app.get("/functions/search")
async def search_functions(
    name: str = Query(..., min_length=1),
    package: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100)
):
    """Search for functions by name.
    
    Parameters:
        name: Function name to search for
        package: Optional package filter
        limit: Maximum results to return
    """
    graph = load_graph()
    functions = graph["functions"]
    
    matches = [
        (fid, f) for fid, f in functions.items()
        if name.lower() in f["name"].lower() and
           (package is None or f["package"] == package)
    ][:limit]
    
    if not matches:
        raise HTTPException(status_code=404, detail=f"Function '{name}' not found")
    
    return {
        "query": name,
        "package_filter": package,
        "results": [
            {
                "id": fid,
                "name": f["name"],
                "package": f["package"],
                "location": f["location"],
                "caller_count": len(f["callers"]),
                "callee_count": len(f["callees"])
            }
            for fid, f in matches
        ]
    }


@app.get("/functions/{func_id}/callers")
async def get_function_callers(
    func_id: str,
    depth: int = Query(1, ge=1, le=5)
):
    """Get callers of a specific function.
    
    Parameters:
        func_id: Function ID (URL encoded)
        depth: Recursion depth for transitive callers
    """
    graph = load_graph()
    functions = graph["functions"]
    
    # URL decode the function ID
    import urllib.parse
    func_id = urllib.parse.unquote(func_id)
    
    if func_id not in functions:
        raise HTTPException(status_code=404, detail=f"Function '{func_id}' not found")
    
    target_func = functions[func_id]
    direct_callers = target_func["callers"]
    
    # For depth > 1, collect transitive callers
    extended_callers = set(direct_callers)
    if depth > 1:
        queue = list(direct_callers)
        for _ in range(depth - 1):
            next_queue = []
            for caller_id in queue:
                if caller_id in functions:
                    new_callers = set(functions[caller_id]["callers"]) - extended_callers
                    extended_callers.update(new_callers)
                    next_queue.extend(new_callers)
            queue = next_queue
    
    return {
        "function": {
            "id": func_id,
            "name": target_func["name"],
            "package": target_func["package"]
        },
        "direct_callers": direct_callers,
        "all_callers_depth_{depth}": list(extended_callers),
        "caller_details": [
            {
                "id": caller_id,
                "name": functions[caller_id]["name"],
                "package": functions[caller_id]["package"],
                "location": functions[caller_id]["location"]
            }
            for caller_id in list(direct_callers)[:20]
        ]
    }


@app.get("/functions/{func_id}/callees")
async def get_function_callees(
    func_id: str,
    depth: int = Query(1, ge=1, le=5)
):
    """Get callees (functions called by) a specific function.
    
    Parameters:
        func_id: Function ID (URL encoded)
        depth: Recursion depth for transitive callees
    """
    graph = load_graph()
    functions = graph["functions"]
    
    import urllib.parse
    func_id = urllib.parse.unquote(func_id)
    
    if func_id not in functions:
        raise HTTPException(status_code=404, detail=f"Function '{func_id}' not found")
    
    target_func = functions[func_id]
    direct_callees = target_func["callees"]
    
    # For depth > 1, collect transitive callees
    extended_callees = set(direct_callees)
    if depth > 1:
        queue = list(direct_callees)
        for _ in range(depth - 1):
            next_queue = []
            for callee_id in queue:
                if callee_id in functions:
                    new_callees = set(functions[callee_id]["callees"]) - extended_callees
                    extended_callees.update(new_callees)
                    next_queue.extend(new_callees)
            queue = next_queue
    
    return {
        "function": {
            "id": func_id,
            "name": target_func["name"],
            "package": target_func["package"]
        },
        "direct_callees": direct_callees,
        "all_callees_depth_{depth}": list(extended_callees),
        "callee_details": [
            {
                "id": callee_id,
                "name": functions[callee_id]["name"],
                "package": functions[callee_id]["package"],
                "location": functions[callee_id]["location"]
            }
            for callee_id in list(direct_callees)[:20]
        ]
    }


# ============================================================================
# Analysis Endpoints
# ============================================================================

@app.get("/analyze/critical-functions")
async def get_critical_functions(
    min_callers: int = Query(3, ge=1),
    limit: int = Query(50, ge=1, le=1000)
):
    """Find functions that are called by many other functions.
    
    These are typically critical utility functions.
    """
    graph = load_graph()
    functions = graph["functions"]
    
    critical = sorted(
        functions.values(),
        key=lambda f: len(f["callers"]),
        reverse=True
    )
    critical = [f for f in critical if len(f["callers"]) >= min_callers][:limit]
    
    return {
        "analysis": "critical_functions",
        "min_callers": min_callers,
        "results": [
            {
                "name": f["name"],
                "package": f["package"],
                "location": f["location"],
                "caller_count": len(f["callers"])
            }
            for f in critical
        ]
    }


@app.get("/analyze/entry-points")
async def get_entry_points(
    package: Optional[str] = None,
    limit: int = Query(50, ge=1, le=1000)
):
    """Find functions that aren't called by any other function.
    
    These are typically public API entry points.
    """
    graph = load_graph()
    functions = graph["functions"]
    
    entries = [
        f for f in functions.values()
        if len(f["callers"]) == 0 and (package is None or f["package"] == package)
    ][:limit]
    
    return {
        "analysis": "entry_points",
        "package_filter": package,
        "results": [
            {
                "name": f["name"],
                "package": f["package"],
                "location": f["location"],
                "callee_count": len(f["callees"])
            }
            for f in entries
        ]
    }


@app.get("/analyze/leaf-functions")
async def get_leaf_functions(
    package: Optional[str] = None,
    limit: int = Query(50, ge=1, le=1000)
):
    """Find functions that don't call any other functions.
    
    These are typically primitive operations or I/O functions.
    """
    graph = load_graph()
    functions = graph["functions"]
    
    leaves = [
        f for f in functions.values()
        if len(f["callees"]) == 0 and (package is None or f["package"] == package)
    ][:limit]
    
    return {
        "analysis": "leaf_functions",
        "package_filter": package,
        "results": [
            {
                "name": f["name"],
                "package": f["package"],
                "location": f["location"],
                "caller_count": len(f["callers"])
            }
            for f in leaves
        ]
    }


# ============================================================================
# Type Query Endpoints
# ============================================================================

@app.get("/types/search")
async def search_types(
    name: str = Query(..., min_length=1),
    package: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100)
):
    """Search for types by name."""
    graph = load_graph()
    types = graph["types"]
    
    matches = [
        (tid, t) for tid, t in types.items()
        if name.lower() in t["name"].lower() and
           (package is None or t["package"] == package)
    ][:limit]
    
    if not matches:
        raise HTTPException(status_code=404, detail=f"Type '{name}' not found")
    
    return {
        "query": name,
        "results": [
            {
                "id": tid,
                "name": t["name"],
                "package": t["package"],
                "kind": t["kind"],
                "location": t["location"],
                "method_count": len(t["methods"])
            }
            for tid, t in matches
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
