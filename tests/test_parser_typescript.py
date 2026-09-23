"""Tests for JavaScriptParser on TypeScript / TSX files."""

from pathlib import Path

import pytest

from codeprism.core.models import EdgeKind, NodeKind

TS_FIXTURE = Path(__file__).parent / "fixtures" / "sample_ts_project" / "api.ts"

pytestmark = pytest.mark.skipif(
    not __import__("importlib").util.find_spec("tree_sitter_typescript"),
    reason="tree-sitter-typescript not installed",
)


@pytest.fixture
def parser():
    from codeprism.parser.javascript_parser import JavaScriptParser
    return JavaScriptParser()


@pytest.fixture
def result(parser):
    content = TS_FIXTURE.read_text(encoding="utf-8")
    return parser.parse(str(TS_FIXTURE), content)


# ── File record ────────────────────────────────────────────────────────────────


def test_file_language_is_typescript(result):
    assert result.file.language == "typescript"


def test_file_checksum_set(result):
    assert result.file.checksum


# ── Interface extraction ───────────────────────────────────────────────────────


def test_interface_user_found(result):
    names = {s.name for s in result.symbols}
    assert "User" in names


def test_interface_kind_is_type(result):
    user = next(s for s in result.symbols if s.name == "User")
    assert user.kind == NodeKind.TYPE


def test_interface_signature_contains_interface(result):
    user = next(s for s in result.symbols if s.name == "User")
    assert "interface" in (user.signature or "").lower()


# ── Type alias extraction ──────────────────────────────────────────────────────


def test_type_alias_user_id_found(result):
    names = {s.name for s in result.symbols}
    assert "UserId" in names


def test_type_alias_kind_is_type(result):
    uid = next(s for s in result.symbols if s.name == "UserId")
    assert uid.kind == NodeKind.TYPE


# ── Class extraction ───────────────────────────────────────────────────────────


def test_class_user_service_found(result):
    names = {s.name for s in result.symbols}
    assert "UserService" in names


def test_class_kind(result):
    cls = next(s for s in result.symbols if s.name == "UserService")
    assert cls.kind == NodeKind.CLASS


# ── Method extraction ──────────────────────────────────────────────────────────


def test_method_add_user_found(result):
    names = {s.name for s in result.symbols}
    assert "addUser" in names


def test_method_get_user_found(result):
    names = {s.name for s in result.symbols}
    assert "getUser" in names


def test_method_is_function_kind(result):
    m = next(s for s in result.symbols if s.name == "addUser")
    assert m.kind == NodeKind.FUNCTION


# ── Arrow function / async function ───────────────────────────────────────────


def test_async_arrow_function_found(result):
    names = {s.name for s in result.symbols}
    assert "fetchUser" in names


def test_async_function_kind(result):
    fn = next(s for s in result.symbols if s.name == "fetchUser")
    assert fn.kind == NodeKind.FUNCTION


# ── Const variable extraction ──────────────────────────────────────────────────


def test_const_default_timeout_found(result):
    names = {s.name for s in result.symbols}
    assert "DEFAULT_TIMEOUT" in names


# ── Import extraction ──────────────────────────────────────────────────────────


def test_import_event_emitter_found(result):
    imports = [s for s in result.symbols if s.kind == NodeKind.IMPORT]
    names = {s.name for s in imports}
    assert "EventEmitter" in names


# ── Edges ──────────────────────────────────────────────────────────────────────


def test_defines_edges_present(result):
    assert any(e.kind == EdgeKind.DEFINES for e in result.edges)


def test_no_errors_during_parse(result):
    assert result.file is not None


# ── Integration: index a TS project ───────────────────────────────────────────


async def test_index_typescript_project(storage, graph, tmp_path):
    import shutil
    from codeprism.core.config import CodePrismConfig
    from codeprism.indexer.project_indexer import ProjectIndexer

    proj = tmp_path / "ts_proj"
    shutil.copytree(TS_FIXTURE.parent, proj)

    config = CodePrismConfig(languages=["typescript"])
    indexer = ProjectIndexer(graph, storage, config)
    result = await indexer.index(str(proj))

    assert result.file_count == 1
    syms = await storage.get_all_symbols()
    names = {s.name for s in syms}
    assert "UserService" in names
    assert "fetchUser" in names
