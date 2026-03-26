"""Parser module initialization."""

from .go_parser import GoCodeParser
from .ast_visitor import GoAstVisitor

__all__ = ["GoCodeParser", "GoAstVisitor"]
