"""Code graph data structures for semantic analysis."""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Set
from enum import Enum
from datetime import datetime


class CallType(str, Enum):
    """Types of function calls in the code graph."""
    DIRECT_CALL = "direct_call"
    METHOD_CALL = "method_call"
    INTERFACE_CALL = "interface_call"
    CLOSURE_CALL = "closure_call"


class SymbolKind(str, Enum):
    """Kinds of symbols in Go code."""
    FUNCTION = "function"
    METHOD = "method"
    STRUCT = "struct"
    INTERFACE = "interface"
    TYPE_ALIAS = "type_alias"
    CONSTANT = "constant"
    VARIABLE = "variable"


@dataclass
class Location:
    """File location of a symbol."""
    file: str  # Relative path
    line: int
    column: int
    end_line: int
    end_column: int

    def to_dict(self):
        return asdict(self)


@dataclass
class TypeNode:
    """Represents a type definition in the code."""
    id: str  # Unique identifier: "file:package:typeName"
    name: str
    package: str
    location: Location
    kind: SymbolKind  # struct, interface, type_alias
    doc: str = ""
    fields: List[Dict] = field(default_factory=list)  # For struct fields
    methods: List[str] = field(default_factory=list)  # Method IDs
    implements: List[str] = field(default_factory=list)  # Interface IDs this type implements

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "package": self.package,
            "location": self.location.to_dict(),
            "kind": self.kind.value,
            "doc": self.doc,
            "fields": self.fields,
            "methods": self.methods,
            "implements": self.implements,
        }


@dataclass
class FunctionNode:
    """Represents a function or method in the code."""
    id: str  # Unique identifier: "file:package:functionName"
    name: str
    package: str
    location: Location
    signature: str  # Full function signature
    doc: str = ""
    receiver: Optional[str] = None  # For methods: the type receiver
    is_method: bool = False
    callers: Set[str] = field(default_factory=set)  # IDs of functions that call this
    callees: Set[str] = field(default_factory=set)  # IDs of functions this calls
    referred_types: Set[str] = field(default_factory=set)  # Type IDs referenced

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "package": self.package,
            "location": self.location.to_dict(),
            "signature": self.signature,
            "doc": self.doc,
            "receiver": self.receiver,
            "is_method": self.is_method,
            "callers": sorted(list(self.callers)),
            "callees": sorted(list(self.callees)),
            "referred_types": sorted(list(self.referred_types)),
        }


@dataclass
class CallEdge:
    """Represents a function call relationship."""
    from_id: str  # Caller function ID
    to_id: str  # Callee function ID
    call_type: CallType
    line: int
    column: int

    def to_dict(self):
        return {
            "from": self.from_id,
            "to": self.to_id,
            "call_type": self.call_type.value,
            "line": self.line,
            "column": self.column,
        }


class CodeGraph:
    """Main code graph structure representing analyzed source code."""

    def __init__(self, repository: str = "kubernetes/kubernetes"):
        self.repository = repository
        self.created_at = datetime.utcnow().isoformat()
        self.functions: Dict[str, FunctionNode] = {}
        self.types: Dict[str, TypeNode] = {}
        self.calls: Dict[str, CallEdge] = {}
        self.packages: Set[str] = set()

    def add_function(self, func: FunctionNode) -> None:
        """Add a function node to the graph."""
        self.functions[func.id] = func
        self.packages.add(func.package)

    def add_type(self, type_node: TypeNode) -> None:
        """Add a type node to the graph."""
        self.types[type_node.id] = type_node
        self.packages.add(type_node.package)

    def add_call(self, call: CallEdge) -> None:
        """Add a call edge to the graph."""
        edge_id = f"{call.from_id}->{call.to_id}"
        self.calls[edge_id] = call
        
        # Update bidirectional references
        if call.from_id in self.functions and call.to_id in self.functions:
            self.functions[call.from_id].callees.add(call.to_id)
            self.functions[call.to_id].callers.add(call.from_id)

    def get_callers(self, function_id: str) -> List[FunctionNode]:
        """Get all functions that call a given function."""
        if function_id not in self.functions:
            return []
        caller_ids = self.functions[function_id].callers
        return [self.functions[cid] for cid in caller_ids if cid in self.functions]

    def get_callees(self, function_id: str) -> List[FunctionNode]:
        """Get all functions called by a given function."""
        if function_id not in self.functions:
            return []
        callee_ids = self.functions[function_id].callees
        return [self.functions[cid] for cid in callee_ids if cid in self.functions]

    def find_functions_by_name(self, name: str, package: Optional[str] = None) -> List[FunctionNode]:
        """Find functions by name, optionally filtered by package."""
        matches = []
        for func in self.functions.values():
            if func.name == name:
                if package is None or func.package == package:
                    matches.append(func)
        return matches

    def find_types_by_name(self, name: str, package: Optional[str] = None) -> List[TypeNode]:
        """Find types by name, optionally filtered by package."""
        matches = []
        for type_node in self.types.values():
            if type_node.name == name:
                if package is None or type_node.package == package:
                    matches.append(type_node)
        return matches

    def to_dict(self):
        """Serialize graph to dictionary."""
        return {
            "version": "1.0",
            "metadata": {
                "created_at": self.created_at,
                "repository": self.repository,
                "packages": sorted(list(self.packages)),
                "total_functions": len(self.functions),
                "total_types": len(self.types),
                "total_calls": len(self.calls),
            },
            "functions": {fid: f.to_dict() for fid, f in self.functions.items()},
            "types": {tid: t.to_dict() for tid, t in self.types.items()},
            "calls": {cid: c.to_dict() for cid, c in self.calls.items()},
        }

    def stats(self) -> Dict:
        """Get statistics about the graph."""
        return {
            "packages": len(self.packages),
            "functions": len(self.functions),
            "types": len(self.types),
            "calls": len(self.calls),
            "avg_callers_per_function": (
                sum(len(f.callers) for f in self.functions.values()) / len(self.functions)
                if self.functions
                else 0
            ),
            "avg_callees_per_function": (
                sum(len(f.callees) for f in self.functions.values()) / len(self.functions)
                if self.functions
                else 0
            ),
        }
