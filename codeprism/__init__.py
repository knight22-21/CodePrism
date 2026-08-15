"""CodePrism — persistent knowledge graph for AI coding agents."""

from .core import (
    CodePrismConfig,
    EdgeKind,
    EdgeRecord,
    FileRecord,
    GraphEngine,
    GraphStats,
    NodeKind,
    SecurityIssue,
    SessionEvent,
    Severity,
    StorageManager,
    SymbolRecord,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "CodePrismConfig",
    "GraphEngine",
    "StorageManager",
    "NodeKind",
    "EdgeKind",
    "Severity",
    "FileRecord",
    "SymbolRecord",
    "EdgeRecord",
    "SecurityIssue",
    "SessionEvent",
    "GraphStats",
]
