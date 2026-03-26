"""AST visitor for extracting semantic information from Go code."""

import re
from pathlib import Path
from typing import List, Tuple, Optional, Set
from tree_sitter import Node

from ..graph import (
    FunctionNode, TypeNode, CallEdge, Location,
    SymbolKind, CallType
)


class GoAstVisitor:
    """Traverses Go AST and extracts code information."""

    def __init__(self, repo_root: Path, parser):
        self.repo_root = Path(repo_root) if not isinstance(repo_root, Path) else repo_root
        self.parser = parser
        self.current_package = ""
        self.current_file = ""
        self.current_source = ""
        self.functions: List[FunctionNode] = []
        self.types: List[TypeNode] = []
        self.calls: List[CallEdge] = []

    def visit(self, node: Node, filepath: Path, source_code: str) -> Tuple[List[FunctionNode], List[TypeNode], List[CallEdge]]:
        """Visit AST and extract information.
        
        Args:
            node: Root node of the AST
            filepath: Path to the source file
            source_code: Source code content
            
        Returns:
            Tuple of (functions, types, calls)
        """
        self.functions = []
        self.types = []
        self.calls = []
        self.current_file = str(filepath.relative_to(self.repo_root)).replace('\\', '/')
        self.current_source = source_code
        self.current_package = self._extract_package_name(source_code)

        self._visit_node(node)

        return self.functions, self.types, self.calls

    def _visit_node(self, node: Node) -> None:
        """Recursively visit AST nodes."""
        if node.type == "source_file":
            self._visit_source_file(node)
        elif node.type == "function_declaration":
            self._visit_function_declaration(node)
        elif node.type == "method_declaration":
            self._visit_method_declaration(node)
        elif node.type == "type_declaration":
            self._visit_type_declaration(node)
        elif node.type == "call_expression":
            self._visit_call_expression(node)

        # Continue visiting children
        for child in node.children:
            self._visit_node(child)

    def _visit_source_file(self, node: Node) -> None:
        """Process source file node."""
        # Extract package declaration
        for child in node.children:
            if child.type == "package_clause":
                package_node = child
                for inner_child in package_node.children:
                    if inner_child.type == "package_identifier":
                        self.current_package = self._get_node_text(inner_child)
                break

    def _visit_function_declaration(self, node: Node) -> None:
        """Extract function declaration."""
        name = None
        signature = ""
        doc = ""
        start_line = node.start_point[0] + 1
        start_col = node.start_point[1]
        end_line = node.end_point[0] + 1
        end_col = node.end_point[1]

        # Extract function name
        for child in node.children:
            if child.type == "identifier":
                name = self._get_node_text(child)
                break

        if not name:
            return

        # Extract signature
        signature = self._get_node_text(node)[:100]  # First 100 chars

        # Create function node
        func_id = f"{self.current_file}:{self.current_package}:{name}"
        location = Location(self.current_file, start_line, start_col, end_line, end_col)

        func = FunctionNode(
            id=func_id,
            name=name,
            package=self.current_package,
            location=location,
            signature=signature,
            doc=doc,
            receiver=None,
            is_method=False
        )

        self.functions.append(func)

        # Extract function calls within this function
        self._extract_calls_from_function(node, func_id)

    def _visit_method_declaration(self, node: Node) -> None:
        """Extract method declaration."""
        name = None
        receiver = None
        signature = ""
        doc = ""
        start_line = node.start_point[0] + 1
        start_col = node.start_point[1]
        end_line = node.end_point[0] + 1
        end_col = node.end_point[1]

        children = node.children
        
        # Extract receiver: assume pattern like func (r *ReceiverType) MethodName
        for i, child in enumerate(children):
            if child.type == "parameter_list":
                # This is the receiver
                receiver = self._extract_receiver_name(child)
            elif child.type == "identifier":
                name = self._get_node_text(child)
                break

        if not name:
            return

        signature = self._get_node_text(node)[:100]

        # Create method node
        func_id = f"{self.current_file}:{self.current_package}:{name}"
        location = Location(self.current_file, start_line, start_col, end_line, end_col)

        func = FunctionNode(
            id=func_id,
            name=name,
            package=self.current_package,
            location=location,
            signature=signature,
            doc=doc,
            receiver=receiver,
            is_method=True
        )

        self.functions.append(func)

        # Extract calls within this method
        self._extract_calls_from_function(node, func_id)

    def _visit_type_declaration(self, node: Node) -> None:
        """Extract type declaration (struct, interface, type alias)."""
        type_spec = None
        for child in node.children:
            if child.type == "type_spec":
                type_spec = child
                break

        if not type_spec:
            return

        name = None
        kind = None
        start_line = node.start_point[0] + 1
        start_col = node.start_point[1]

        # Extract type name
        for child in type_spec.children:
            if child.type == "type_identifier":
                name = self._get_node_text(child)
            elif child.type == "struct_type":
                kind = SymbolKind.STRUCT
            elif child.type == "interface_type":
                kind = SymbolKind.INTERFACE
            else:
                # Default for type aliases
                if kind is None:
                    kind = SymbolKind.TYPE_ALIAS

        if not name or not kind:
            return

        type_id = f"{self.current_file}:{self.current_package}:{name}"
        location = Location(self.current_file, start_line, start_col, node.end_point[0] + 1, node.end_point[1])

        type_node = TypeNode(
            id=type_id,
            name=name,
            package=self.current_package,
            location=location,
            kind=kind,
            doc=""
        )

        self.types.append(type_node)

    def _visit_call_expression(self, node: Node) -> None:
        """Extract function call - Note: this is called during recursion."""
        # Call expressions are handled via _extract_calls_from_function
        # This is here as a placeholder for direct handling
        pass

    def _extract_calls_from_function(self, func_node: Node, caller_id: str) -> None:
        """Extract all function calls within a function body."""
        # Find the function body
        body = None
        for child in func_node.children:
            if child.type == "block":
                body = child
                break

        if not body:
            return

        self._extract_calls_from_block(body, caller_id)

    def _extract_calls_from_block(self, block_node: Node, caller_id: str) -> None:
        """Recursively extract calls from a code block."""
        for child in block_node.children:
            if child.type == "call_expression":
                call_info = self._extract_call_info(child, caller_id)
                if call_info:
                    self.calls.append(call_info)
            elif child.type == "block":
                self._extract_calls_from_block(child, caller_id)
            # Recursively handle other block types (if, for, etc.)
            elif hasattr(child, 'children'):
                self._extract_calls_from_block(child, caller_id)

    def _extract_call_info(self, call_node: Node, caller_id: str) -> Optional[CallEdge]:
        """Extract information from a call expression."""
        try:
            line = call_node.start_point[0] + 1
            col = call_node.start_point[1]

            # Get the function name being called
            func_text = self._get_node_text(call_node)
            call_name = self._extract_function_name_from_call(call_node)

            if not call_name:
                return None

            # Determine call type and create a generic callee ID
            # In a full implementation, we'd resolve this to actual function IDs
            callee_id = f"{self.current_file}:{self.current_package}:{call_name}"

            call_type = CallType.DIRECT_CALL
            if "." in call_name:
                call_type = CallType.METHOD_CALL

            return CallEdge(
                from_id=caller_id,
                to_id=callee_id,
                call_type=call_type,
                line=line,
                column=col
            )
        except Exception:
            return None

    def _extract_function_name_from_call(self, call_node: Node) -> Optional[str]:
        """Extract the function name from a call expression."""
        # call_expression has structure: func arguments
        # func can be identifier, selector_expression, etc.
        if not call_node.children:
            return None

        func_part = call_node.children[0]

        if func_part.type == "identifier":
            return self._get_node_text(func_part)
        elif func_part.type == "selector_expression":
            # Method or package-qualified call
            # selector_expression: object . field
            text = self._get_node_text(func_part)
            # Extract just the method name (after the dot)
            if "." in text:
                return text.split(".")[-1]
            return text

        return None

    def _extract_receiver_name(self, param_list: Node) -> Optional[str]:
        """Extract receiver type from parameter list."""
        try:
            text = self._get_node_text(param_list)
            # Remove parentheses and extract type
            # Pattern: (r *ReceiverType) or (r ReceiverType)
            match = re.search(r'\*?\s*([A-Za-z_]\w*)', text)
            return match.group(1) if match else None
        except Exception:
            return None

    def _extract_package_name(self, source_code: str) -> str:
        """Extract package name from source code."""
        match = re.search(r'^\s*package\s+([a-zA-Z_]\w*)', source_code, re.MULTILINE)
        return match.group(1) if match else "main"

    def _get_node_text(self, node: Node) -> str:
        """Get text content of a node."""
        try:
            start_byte = node.start_byte
            end_byte = node.end_byte
            return self.current_source[start_byte:end_byte]
        except Exception:
            return ""
