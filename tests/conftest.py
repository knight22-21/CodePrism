import shutil
import pytest
from pathlib import Path

from codeprism.core.storage import StorageManager
from codeprism.core.graph import GraphEngine
from codeprism.core.models import FileRecord, SymbolRecord, EdgeRecord, NodeKind, EdgeKind

PYTHON_FIXTURE = Path(__file__).parent / "fixtures" / "sample_python_project"


@pytest.fixture
async def indexed_engine(tmp_path: Path):
    """Return (QueryEngine, StorageManager) for the sample Python project."""
    from codeprism.core.config import CodePrismConfig
    from codeprism.indexer.project_indexer import ProjectIndexer
    from codeprism.query.engine import QueryEngine

    proj = tmp_path / "project"
    shutil.copytree(PYTHON_FIXTURE, proj)

    db = StorageManager(tmp_path / "idx.db")
    await db.initialize()
    g = GraphEngine()
    config = CodePrismConfig(languages=["python"])
    await ProjectIndexer(g, db, config).index(str(proj))
    engine = QueryEngine(g, db)
    yield engine, db, proj
    await db.close()


@pytest.fixture
async def storage(tmp_path: Path) -> StorageManager:
    mgr = StorageManager(tmp_path / "test.db")
    await mgr.initialize()
    yield mgr
    await mgr.close()


@pytest.fixture
def graph() -> GraphEngine:
    return GraphEngine()


# ── Shared factories ──────────────────────────────────────────────────────────

def make_file(path: str = "/project/main.py", language: str = "python") -> FileRecord:
    return FileRecord.create(path=path, language=language, line_count=100)


def make_symbol(
    name: str,
    kind: NodeKind = NodeKind.FUNCTION,
    file: FileRecord | None = None,
    file_path: str = "/project/main.py",
) -> SymbolRecord:
    if file is None:
        file = make_file(file_path)
    return SymbolRecord.create(
        file_path=file.path,
        file_id=file.id,
        name=name,
        kind=kind,
        line_start=1,
        line_end=10,
    )


def make_edge(
    from_sym: SymbolRecord,
    to_sym: SymbolRecord,
    kind: EdgeKind = EdgeKind.CALLS,
    file_path: str = "/project/main.py",
    line: int = 5,
) -> EdgeRecord:
    return EdgeRecord.create(
        kind=kind, from_id=from_sym.id, to_id=to_sym.id, file_path=file_path, line_number=line
    )
