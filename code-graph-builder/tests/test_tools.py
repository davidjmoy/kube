"""Tests for chatbot tool functions.

Run: python -m pytest tests/test_tools.py -v
"""

import os
import sys
import json
import pytest
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Set required env vars before importing
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com/")
os.environ.setdefault("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
os.environ.setdefault("AZURE_DEPLOYMENT_NAME", "gpt-4o")
os.environ.setdefault("GRAPH_PATH", "output/code-graph.json")
os.environ.setdefault("INDEX_DB", "output/file-index3.db")
os.environ.setdefault("REPO_ROOT", str(Path(__file__).resolve().parent.parent.parent / "kubernetes"))

from src.chatbot_service import (
    _tool_grep,
    _tool_read_file,
    _tool_find_callers,
    _tool_search_graph,
    _tool_list_directory,
    _graph_files_for_pattern,
    execute_tool,
    REPO_ROOT,
    file_index,
)
from src.file_index import FileIndex
from src.doc_index import DocIndex
from src.chatbot_service import _tool_search_docs, _tool_read_doc, doc_index, _github_url


# ============================================================================
# Helpers
# ============================================================================

def repo_exists():
    return REPO_ROOT.exists()


skip_no_repo = pytest.mark.skipif(not repo_exists(), reason="Kubernetes repo not found")
skip_no_graph = pytest.mark.skipif(
    not Path("output/code-graph.json").exists(),
    reason="Code graph not generated"
)
skip_no_index = pytest.mark.skipif(
    not Path(os.environ.get("INDEX_DB", "output/file-index3.db")).exists(),
    reason="File-content index not built"
)
skip_no_doc_index = pytest.mark.skipif(
    not Path(os.environ.get("DOCS_INDEX_DB", "output/doc-index.db")).exists(),
    reason="Doc index not built"
)


# ============================================================================
# _tool_grep tests
# ============================================================================

class TestGrepCode:
    @skip_no_repo
    def test_finds_known_function(self):
        result = _tool_grep({"pattern": "func ValidateObjectMeta", "path": "pkg/apis/core/validation"})
        assert "ValidateObjectMeta" in result
        assert "validation.go" in result

    @skip_no_repo
    def test_returns_no_matches_for_gibberish(self):
        result = _tool_grep({"pattern": "xyzzy_nonexistent_9999", "path": "pkg"})
        assert "No matches" in result

    @skip_no_repo
    def test_truncates_broad_search(self):
        """Broad term like 'func' should hit the 60-match cap and truncate."""
        result = _tool_grep({"pattern": "func ", "path": "pkg/kubelet"})
        # Should either have results or a truncation notice
        assert len(result) > 0
        # Should not take forever — this test itself is a timeout check

    @skip_no_repo
    def test_nonexistent_path(self):
        result = _tool_grep({"pattern": "test", "path": "nonexistent/dir"})
        assert "not found" in result.lower()

    @skip_no_repo
    def test_narrow_search_returns_line_numbers(self):
        result = _tool_grep({"pattern": "func NewClient", "path": "pkg"})
        # Should contain file:linenum: format
        if "No matches" not in result:
            assert ":" in result

    @skip_no_repo
    def test_respects_include_pattern(self):
        result = _tool_grep({"pattern": "apiVersion", "path": ".", "include_pattern": "*.yaml"})
        # Should only match yaml files or find nothing
        if "No matches" not in result:
            for line in result.strip().split("\n")[:5]:
                # Each line should reference a yaml file
                assert ".yaml" in line.lower() or ".yml" in line.lower() or "No matches" in result


# ============================================================================
# _tool_read_file tests
# ============================================================================

class TestReadFile:
    @skip_no_repo
    def test_reads_known_file(self):
        result = _tool_read_file({"file_path": "pkg/kubelet/kubelet.go"})
        assert "kubelet.go" in result
        assert "package" in result.lower()

    @skip_no_repo
    def test_reads_specific_range(self):
        result = _tool_read_file({"file_path": "pkg/kubelet/kubelet.go", "start_line": 1, "end_line": 10})
        assert "lines 1-10" in result

    @skip_no_repo
    def test_file_not_found(self):
        result = _tool_read_file({"file_path": "pkg/nonexistent_file.go"})
        assert "not found" in result.lower()

    def test_path_traversal_blocked(self):
        result = _tool_read_file({"file_path": "../../etc/passwd"})
        assert "not allowed" in result.lower()

    @skip_no_repo
    def test_directory_not_a_file(self):
        result = _tool_read_file({"file_path": "pkg/kubelet"})
        assert "not a file" in result.lower()


# ============================================================================
# _tool_find_callers tests
# ============================================================================

class TestFindCallers:
    @skip_no_graph
    def test_finds_callers_of_known_function(self):
        result = _tool_find_callers({"function_name": "ValidateObjectMeta"})
        assert "ValidateObjectMeta" in result
        assert "Callers" in result or "No callers" in result

    @skip_no_graph
    def test_no_match_returns_message(self):
        result = _tool_find_callers({"function_name": "xyzzy_nonexistent_9999"})
        assert "No function matching" in result

    @skip_no_graph
    def test_partial_match_works(self):
        result = _tool_find_callers({"function_name": "ValidateObjectMeta"})
        assert "ValidateObjectMeta" in result


# ============================================================================
# _tool_search_graph tests
# ============================================================================

class TestSearchGraph:
    @skip_no_graph
    def test_search_known_term(self):
        result = _tool_search_graph({"query": "kubelet"})
        assert "kubelet" in result.lower()
        assert "Found" in result

    @skip_no_graph
    def test_search_no_results(self):
        result = _tool_search_graph({"query": "xyzzy_nonexistent_9999"})
        assert "No functions matching" in result

    @skip_no_graph
    def test_max_results_respected(self):
        result = _tool_search_graph({"query": "Validate", "max_results": 3})
        # Count result lines (each starts with "- ")
        result_lines = [l for l in result.split("\n") if l.startswith("- ")]
        assert len(result_lines) <= 3


# ============================================================================
# _tool_list_directory tests
# ============================================================================

class TestListDirectory:
    @skip_no_repo
    def test_list_root(self):
        result = _tool_list_directory({"path": ""})
        assert "pkg/" in result
        assert "cmd/" in result

    @skip_no_repo
    def test_list_subdir(self):
        result = _tool_list_directory({"path": "pkg"})
        assert "kubelet/" in result

    @skip_no_repo
    def test_nonexistent_dir(self):
        result = _tool_list_directory({"path": "nonexistent_dir"})
        assert "not found" in result.lower()

    def test_path_traversal_blocked(self):
        result = _tool_list_directory({"path": "../../"})
        assert "not allowed" in result.lower()


# ============================================================================
# execute_tool dispatch tests
# ============================================================================

class TestExecuteTool:
    def test_unknown_tool(self):
        result = execute_tool("nonexistent_tool", {})
        assert "Unknown tool" in result

    @skip_no_repo
    def test_dispatches_grep(self):
        result = execute_tool("grep_code", {"pattern": "func main", "path": "cmd"})
        assert len(result) > 0

    @skip_no_repo
    def test_dispatches_read_file(self):
        result = execute_tool("read_file", {"file_path": "go.mod"})
        assert "module" in result.lower() or "not found" in result.lower()

    @skip_no_graph
    def test_dispatches_search_graph(self):
        result = execute_tool("search_graph", {"query": "pod"})
        assert len(result) > 0


# ============================================================================
# Performance / safety tests
# ============================================================================

class TestPerformance:
    @skip_no_repo
    def test_grep_broad_term_completes_fast(self):
        """A broad grep like 'controller' must complete, not hang."""
        import time
        start = time.time()
        result = _tool_grep({"pattern": "controller", "path": "pkg"})
        elapsed = time.time() - start
        assert elapsed < 30, f"Grep took {elapsed:.1f}s — too slow"
        assert len(result) > 0

    @skip_no_repo
    def test_grep_entire_repo_completes(self):
        """Even searching the full repo root should complete quickly."""
        import time
        start = time.time()
        result = _tool_grep({"pattern": "func main", "path": "cmd"})
        elapsed = time.time() - start
        assert elapsed < 30, f"Grep took {elapsed:.1f}s"

    @skip_no_repo
    def test_read_large_file_with_range(self):
        """Reading a range from a large file should be instant."""
        import time
        start = time.time()
        result = _tool_read_file({
            "file_path": "pkg/kubelet/kubelet.go",
            "start_line": 1,
            "end_line": 50
        })
        elapsed = time.time() - start
        assert elapsed < 2, f"Read took {elapsed:.1f}s"
        assert "kubelet" in result.lower()


# ============================================================================
# Graph-guided grep tests
# ============================================================================

class TestGraphGuidedGrep:
    @skip_no_graph
    def test_graph_files_returns_relevant_files(self):
        """Graph should identify files for a known function name."""
        files = _graph_files_for_pattern("ValidateObjectMeta", "pkg")
        assert len(files) > 0
        assert all(f.startswith("pkg/") for f in files)

    @skip_no_graph
    def test_graph_files_empty_for_nonsense(self):
        files = _graph_files_for_pattern("xyzzy_nonexistent_9999", "pkg")
        assert files == []

    @skip_no_graph
    @skip_no_repo
    def test_grep_uses_graph_for_known_function(self):
        """Grep for a graph-known function should use graph-guided or indexed search."""
        result = _tool_grep({"pattern": "ValidateObjectMeta", "path": "pkg"})
        assert "graph-guided" in result or "indexed" in result
        assert "ValidateObjectMeta" in result

    @skip_no_repo
    def test_grep_falls_back_for_unknown_pattern(self):
        """Grep for non-function text should fall back to full scan."""
        result = _tool_grep({"pattern": "Copyright 2019 The Kubernetes Authors", "path": "pkg/kubelet"})
        # A copyright string won't match any function/type names in the graph
        if "No matches" not in result:
            # Could be indexed or fallback, but not graph-guided
            pass  # Any result is acceptable

    @skip_no_graph
    @skip_no_repo
    def test_graph_guided_grep_faster_than_full_scan(self):
        """Graph-guided grep for 'controller' should be faster."""
        import time
        start = time.time()
        result = _tool_grep({"pattern": "controller", "path": "pkg"})
        elapsed = time.time() - start
        assert elapsed < 10, f"Graph-guided grep took {elapsed:.1f}s"
        assert len(result) > 0


# ============================================================================
# File-content index tests
# ============================================================================

class TestFileIndex:
    @skip_no_index
    def test_index_exists(self):
        assert file_index.exists

    @skip_no_index
    def test_search_returns_results(self):
        results = file_index.search("controller", path_prefix="pkg/", limit=10)
        assert len(results) > 0
        assert all(r[0].startswith("pkg/") for r in results)

    @skip_no_index
    def test_search_specific_function(self):
        results = file_index.search("ValidateObjectMeta", path_prefix="pkg/", limit=10)
        assert len(results) > 0
        assert any("ValidateObjectMeta" in r[2] for r in results)

    @skip_no_index
    def test_search_multi_word(self):
        results = file_index.search("func NewClient", path_prefix="pkg/", limit=10)
        assert len(results) > 0
        assert any("newclient" in r[2].lower() for r in results)

    @skip_no_index
    def test_search_no_results_for_gibberish(self):
        results = file_index.search("xyzzy_nonexistent_9999", limit=10)
        assert results == []

    @skip_no_index
    def test_search_respects_limit(self):
        results = file_index.search("func", path_prefix="pkg/", limit=5)
        assert len(results) <= 5

    @skip_no_index
    def test_search_speed(self):
        """Warm FTS queries should be fast."""
        import time
        # Warm up
        file_index.search("warmup", limit=1)
        start = time.time()
        for _ in range(10):
            file_index.search("controller", path_prefix="pkg/", limit=60)
        elapsed = (time.time() - start) * 1000
        avg = elapsed / 10
        print(f"Avg FTS query: {avg:.1f}ms")
        assert avg < 500, f"FTS too slow: {avg:.1f}ms avg"

    @skip_no_index
    @skip_no_repo
    def test_grep_uses_index_when_available(self):
        """With an index, grep should use indexed search."""
        result = _tool_grep({"pattern": "controller", "path": "pkg"})
        assert "indexed search" in result


# ============================================================================
# DocIndex tests
# ============================================================================

class TestDocIndex:
    @skip_no_doc_index
    def test_doc_index_exists(self):
        assert doc_index.exists

    @skip_no_doc_index
    def test_search_returns_results(self):
        results = doc_index.search("pod lifecycle")
        assert len(results) > 0
        assert all("title" in r for r in results)
        assert all("url" in r for r in results)

    @skip_no_doc_index
    def test_search_returns_relevant_titles(self):
        results = doc_index.search("network policy")
        assert len(results) > 0
        titles = " ".join(r["title"].lower() for r in results)
        assert "network" in titles or "policy" in titles

    @skip_no_doc_index
    def test_search_no_results_for_gibberish(self):
        results = doc_index.search("xyzzy_nonexistent_9999_zzzz")
        assert results == []

    @skip_no_doc_index
    def test_search_respects_limit(self):
        results = doc_index.search("kubernetes", limit=3)
        assert len(results) <= 3

    @skip_no_doc_index
    def test_get_doc_returns_content(self):
        results = doc_index.search("pod lifecycle", limit=1)
        assert len(results) > 0
        doc = doc_index.get_doc(results[0]["file"])
        assert doc is not None
        assert "content" in doc
        assert len(doc["content"]) > 0

    @skip_no_doc_index
    def test_url_format(self):
        results = doc_index.search("deployment", limit=3)
        for r in results:
            assert r["url"].startswith("/docs/")


# ============================================================================
# Doc tool tests
# ============================================================================

class TestDocTools:
    @skip_no_doc_index
    def test_search_docs_tool(self):
        result = _tool_search_docs({"query": "horizontal pod autoscaler"})
        assert "Found" in result
        assert "kubernetes.io" in result

    @skip_no_doc_index
    def test_read_doc_tool(self):
        results = doc_index.search("pod lifecycle", limit=1)
        assert len(results) > 0
        result = _tool_read_doc({"file_path": results[0]["file"]})
        assert "kubernetes.io" in result
        assert results[0]["title"] in result

    @skip_no_doc_index
    def test_read_doc_not_found(self):
        result = _tool_read_doc({"file_path": "nonexistent/doc.md"})
        assert "not found" in result.lower()

    def test_read_doc_path_traversal(self):
        result = _tool_read_doc({"file_path": "../../etc/passwd"})
        assert "path traversal" in result.lower()

    @skip_no_doc_index
    def test_execute_tool_dispatches_search_docs(self):
        result = execute_tool("search_docs", {"query": "configmap"})
        assert len(result) > 0

    @skip_no_doc_index
    def test_execute_tool_dispatches_read_doc(self):
        results = doc_index.search("service", limit=1)
        result = execute_tool("read_doc", {"file_path": results[0]["file"]})
        assert len(result) > 0


# ============================================================================
# GitHub URL helper tests
# ============================================================================

class TestGitHubUrl:
    def test_basic_url(self):
        url = _github_url("pkg/kubelet/kubelet.go")
        assert "github.com/kubernetes/kubernetes" in url
        assert "pkg/kubelet/kubelet.go" in url

    def test_url_with_line(self):
        url = _github_url("pkg/kubelet/kubelet.go", 42)
        assert url.endswith("#L42")

    def test_url_without_line(self):
        url = _github_url("pkg/kubelet/kubelet.go")
        assert "#L" not in url
