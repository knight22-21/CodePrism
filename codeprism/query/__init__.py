"""Query package — high-level graph query interface."""

from .context import ContextResult, get_context
from .engine import (
    DataFlowResult,
    DependencyResult,
    DependentResult,
    FileMap,
    FileMapEntry,
    QueryEngine,
    SearchMatch,
)
from .impact import ImpactResult, get_impact
from .summary import ModuleSummary, get_module_summary

__all__ = [
    "QueryEngine",
    "ContextResult",
    "ImpactResult",
    "ModuleSummary",
    "SearchMatch",
    "FileMap",
    "FileMapEntry",
    "DependencyResult",
    "DependentResult",
    "DataFlowResult",
    "get_context",
    "get_impact",
    "get_module_summary",
]
