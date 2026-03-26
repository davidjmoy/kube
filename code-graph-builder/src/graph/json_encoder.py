"""JSON serialization for code graphs."""

import json
from typing import Any, Dict
from pathlib import Path

from .code_graph import CodeGraph


class JsonCodeGraphEncoder(json.JSONEncoder):
    """Custom JSON encoder for code graph objects."""

    def default(self, obj: Any) -> Any:
        """Handle serialization of custom objects."""
        if isinstance(obj, set):
            return sorted(list(obj))
        return super().default(obj)


class CodeGraphSerializer:
    """Handles persistence of code graphs."""

    @staticmethod
    def save_graph(graph: CodeGraph, filepath: Path) -> None:
        """Save code graph to JSON file."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(graph.to_dict(), f, indent=2, cls=JsonCodeGraphEncoder)

    @staticmethod
    def load_graph(filepath: Path) -> Dict[str, Any]:
        """Load code graph from JSON file."""
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def save_stats(graph: CodeGraph, filepath: Path) -> None:
        """Save graph statistics to JSON file."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(graph.stats(), f, indent=2, cls=JsonCodeGraphEncoder)
