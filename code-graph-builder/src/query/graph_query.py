"""Query utilities for code graph analysis."""

from typing import List, Optional, Set, Dict
from ..graph import CodeGraph, FunctionNode, TypeNode


class GraphQuery:
    """Query interface for analyzing code graphs."""

    def __init__(self, graph: CodeGraph):
        self.graph = graph

    def find_callers_recursive(self, function_id: str, max_depth: int = 10) -> Dict[str, int]:
        """Find all callers of a function recursively.
        
        Args:
            function_id: ID of the function to analyze
            max_depth: Maximum recursion depth
            
        Returns:
            Dictionary mapping caller IDs to their depth in the call chain
        """
        if function_id not in self.graph.functions:
            return {}

        result = {}
        visited = set()
        queue = [(function_id, 0)]

        while queue:
            curr_id, depth = queue.pop(0)
            if curr_id in visited or depth > max_depth:
                continue

            visited.add(curr_id)

            if curr_id in self.graph.functions:
                for caller_id in self.graph.functions[curr_id].callers:
                    if caller_id not in visited:
                        result[caller_id] = depth + 1
                        queue.append((caller_id, depth + 1))

        return result

    def find_callees_recursive(self, function_id: str, max_depth: int = 10) -> Dict[str, int]:
        """Find all callees of a function recursively.
        
        Args:
            function_id: ID of the function to analyze
            max_depth: Maximum recursion depth
            
        Returns:
            Dictionary mapping callee IDs to their depth in the call chain
        """
        if function_id not in self.graph.functions:
            return {}

        result = {}
        visited = set()
        queue = [(function_id, 0)]

        while queue:
            curr_id, depth = queue.pop(0)
            if curr_id in visited or depth > max_depth:
                continue

            visited.add(curr_id)

            if curr_id in self.graph.functions:
                for callee_id in self.graph.functions[curr_id].callees:
                    if callee_id not in visited:
                        result[callee_id] = depth + 1
                        queue.append((callee_id, depth + 1))

        return result

    def find_call_chains(self, from_id: str, to_id: str, max_depth: int = 5) -> List[List[str]]:
        """Find all call chains from one function to another.
        
        Args:
            from_id: Starting function ID
            to_id: Target function ID
            max_depth: Maximum chain length
            
        Returns:
            List of call chains (each chain is a list of function IDs)
        """
        chains = []
        
        def dfs(current_id: str, target_id: str, path: List[str], depth: int):
            if depth > max_depth or current_id in path[:-1]:  # Avoid cycles
                return

            if current_id == target_id:
                chains.append(path)
                return

            if current_id not in self.graph.functions:
                return

            for callee_id in self.graph.functions[current_id].callees:
                dfs(callee_id, target_id, path + [callee_id], depth + 1)

        dfs(from_id, to_id, [from_id], 0)
        return chains

    def find_functions_by_name_pattern(self, pattern: str, regex: bool = False) -> List[FunctionNode]:
        """Find functions matching a name pattern.
        
        Args:
            pattern: Name pattern or regex
            regex: Whether pattern is a regex
            
        Returns:
            List of matching functions
        """
        if regex:
            import re
            pattern_re = re.compile(pattern)
            return [
                func for func in self.graph.functions.values()
                if pattern_re.search(func.name)
            ]
        else:
            return [
                func for func in self.graph.functions.values()
                if pattern.lower() in func.name.lower()
            ]

    def get_critical_functions(self, min_callers: int = 3) -> List[FunctionNode]:
        """Find functions called by many other functions.
        
        Args:
            min_callers: Minimum number of distinct callers
            
        Returns:
            Sorted list of critical functions
        """
        critical = [
            func for func in self.graph.functions.values()
            if len(func.callers) >= min_callers
        ]
        return sorted(critical, key=lambda f: len(f.callers), reverse=True)

    def get_leaf_functions(self) -> List[FunctionNode]:
        """Find functions that don't call other functions.
        
        Returns:
            List of leaf functions
        """
        return [
            func for func in self.graph.functions.values()
            if len(func.callees) == 0
        ]

    def get_entry_points(self) -> List[FunctionNode]:
        """Find functions that aren't called by any other function.
        
        Returns:
            List of entry point functions
        """
        return [
            func for func in self.graph.functions.values()
            if len(func.callers) == 0
        ]

    def get_package_statistics(self, package: str) -> Dict:
        """Get statistics for a specific package.
        
        Args:
            package: Package name
            
        Returns:
            Dictionary with package statistics
        """
        funcs = [f for f in self.graph.functions.values() if f.package == package]
        types = [t for t in self.graph.types.values() if t.package == package]
        calls = [
            c for c in self.graph.calls.values()
            if self.graph.functions.get(c.from_id, FunctionNode(
                id="", name="", package=package, location=None,
                signature=""
            )).package == package
        ]

        return {
            "package": package,
            "functions": len(funcs),
            "types": len(types),
            "calls": len(calls),
            "avg_callers_per_function": (
                sum(len(f.callers) for f in funcs) / len(funcs) if funcs else 0
            ),
            "avg_callees_per_function": (
                sum(len(f.callees) for f in funcs) / len(funcs) if funcs else 0
            ),
        }
