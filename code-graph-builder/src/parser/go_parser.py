"""Go code parser using tree-sitter."""

import os
from pathlib import Path
from typing import List, Optional
import tree_sitter_go
from tree_sitter import Language, Parser

from ..graph import CodeGraph, FunctionNode, TypeNode, CallEdge, Location, SymbolKind, CallType
from .ast_visitor import GoAstVisitor


class GoCodeParser:
    """Parses Go source files and builds a code graph."""

    def __init__(self, repo_root: str):
        """Initialize the Go parser.
        
        Args:
            repo_root: Root directory of the repository to analyze
        """
        self.repo_root = Path(repo_root)
        
        # Initialize tree-sitter Go parser
        try:
            GO_LANGUAGE = Language(tree_sitter_go.language())
            self.parser = Parser(GO_LANGUAGE)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize tree-sitter Go parser: {e}")

        self.graph = CodeGraph()
        self.visitor = GoAstVisitor(self.repo_root, self.parser)

    def parse_file(self, filepath: Path) -> bool:
        """Parse a single Go file and update the graph.
        
        Args:
            filepath: Path to the Go file
            
        Returns:
            True if parsing succeeded, False otherwise
        """
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                source_code = f.read()
            
            # Parse with tree-sitter
            tree = self.parser.parse(source_code.encode('utf-8'))
            
            # Extract functions, types, and calls
            functions, types, calls = self.visitor.visit(tree.root_node, filepath, source_code)
            
            # Add to graph
            for func in functions:
                self.graph.add_function(func)
            
            for type_node in types:
                self.graph.add_type(type_node)
            
            for call in calls:
                self.graph.add_call(call)
            
            return True
        except Exception as e:
            print(f"Error parsing {filepath}: {e}")
            return False

    def parse_directory(self, directory: Optional[str] = None, recursive: bool = True) -> int:
        """Parse all Go files in a directory.
        
        Args:
            directory: Directory to parse (relative to repo root). If None, uses repo root.
            recursive: Whether to parse recursively
            
        Returns:
            Number of files successfully parsed
        """
        if directory:
            search_path = self.repo_root / directory
        else:
            search_path = self.repo_root

        if not search_path.exists():
            raise ValueError(f"Directory not found: {search_path}")

        parsed_count = 0
        
        if recursive:
            go_files = search_path.rglob("*.go")
        else:
            go_files = search_path.glob("*.go")

        for filepath in go_files:
            # Skip vendor, third_party, generated, and test files for now
            rel_path = filepath.relative_to(self.repo_root)
            path_str = str(rel_path).lower()
            
            if any(skip in path_str for skip in ['vendor/', 'third_party/', '_generated', '_test.go']):
                continue

            if self.parse_file(filepath):
                parsed_count += 1
                if parsed_count % 100 == 0:
                    print(f"Parsed {parsed_count} files...")

        return parsed_count

    def get_graph(self) -> CodeGraph:
        """Get the built code graph."""
        return self.graph

    def resolve_call_references(self) -> None:
        """Resolve call references between functions.
        
        This is called after parsing to link function calls to their definitions.
        """
        # This is partially done during visiting, but we can enhance it here
        # by resolving package-qualified calls and method calls
        pass
