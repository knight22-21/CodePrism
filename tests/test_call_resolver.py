"""Import-aware call resolution: calls link to what the code actually calls."""

from pathlib import Path

import pytest

from codeprism.core.config import CodePrismConfig
from codeprism.core.models import EdgeKind
from codeprism.indexer.call_resolver import ModuleIndex
from codeprism.indexer.project_indexer import ProjectIndexer

FILES = {
    "pkg/__init__.py": "from .facade import Facade\n",
    "pkg/facade.py": "class Facade:\n    def open(self):\n        return 1\n",
    "pkg/text.py": (
        "def join(parts):\n    return ''.join(parts)\n\n"
        "def str(x):\n    return x\n\n"
        "def helper():\n    return 1\n"
    ),
    "pkg/other.py": "def helper():\n    return 2\n\nclass Store:\n    def load(self):\n        return 1\n",
    "pkg/models.py": "class Record:\n    language = 'py'\n",
    "pkg/sub/__init__.py": "",
    "pkg/sub/runner.py": "def run():\n    return 1\n",
    "app/main.py": (
        "import json\n"
        "import os.path\n"
        "from pkg.other import helper\n"
        "from pkg import Facade\n"
        "from pkg.sub import runner\n"
        "from pkg.other import Store\n\n"
        "def uses_builtins(x):\n    return str(x) + json.dumps(x) + os.path.join('a', 'b')\n\n"
        "def uses_import():\n    return helper()\n\n"
        "def uses_reexport():\n    return Facade()\n\n"
        "def uses_module_attr():\n    return runner.run()\n\n"
        "def uses_object(store: Store):\n    return store.load()\n\n"
        "def lazy():\n    from pkg.text import helper as h\n    from pkg.other import helper\n"
        "    return helper()\n\n"
        "def unknown_object(x):\n    return x.language()\n"
    ),
}


@pytest.fixture
async def indexed(storage, graph, tmp_path):
    root = tmp_path / "proj"
    for rel, text in FILES.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    cfg = CodePrismConfig(languages=["python"], respect_gitignore=False)
    await ProjectIndexer(graph, storage, cfg).index(str(root))
    syms = {s.id: s for s in await storage.get_all_symbols()}
    files = {f.id: Path(f.path).relative_to(root).as_posix() for f in await storage.get_all_files()}
    calls: dict[str, set[str]] = {}
    for e in await storage.get_all_edges():
        if e.kind == EdgeKind.CALLS and e.from_id in syms and e.to_id in syms:
            dst = syms[e.to_id]
            calls.setdefault(syms[e.from_id].name, set()).add(f"{files[dst.file_id]}:{dst.name}")
    return calls


async def test_builtins_and_third_party_calls_link_nothing(indexed):
    # str() is a builtin and os.path.join / json.dumps are stdlib, even though
    # the project defines functions called str and join
    assert indexed.get("uses_builtins", set()) == set()


async def test_imported_function_links_to_its_module(indexed):
    # both text.py and other.py define helper(); the import decides. (By name
    # alone, the later-indexed text.py would win.)
    assert indexed["uses_import"] == {"pkg/other.py:helper"}


async def test_reexport_through_package_init(indexed):
    assert indexed["uses_reexport"] == {"pkg/facade.py:Facade"}


async def test_module_attribute_call(indexed):
    assert indexed["uses_module_attr"] == {"pkg/sub/runner.py:run"}


async def test_method_call_on_object_uses_callers_imports(indexed):
    assert indexed["uses_object"] == {"pkg/other.py:load"}


async def test_function_local_imports_are_used(indexed):
    assert indexed["lazy"] == {"pkg/other.py:helper"}


async def test_calls_never_target_fields_or_unimported_files(indexed):
    # Record.language is a field, and models.py isn't imported by main.py
    assert indexed.get("unknown_object", set()) == set()


def test_module_index_resolution(tmp_path):
    root = tmp_path.resolve()
    paths = [
        str(root / p) for p in ("pkg/__init__.py", "pkg/core/storage.py", "pkg/core/__init__.py")
    ]
    idx = ModuleIndex(paths)
    caller = str(root / "pkg/indexer/x.py")
    assert idx.resolve("pkg.core.storage", caller) == [paths[1]]
    assert idx.resolve("..core.storage", caller) == [paths[1]]
    assert idx.resolve("..core", caller) == [paths[2]]
    assert idx.resolve("json", caller) == []


async def test_other_languages_still_resolve_by_name(storage, graph, tmp_path):
    root = tmp_path / "js"
    root.mkdir()
    (root / "a.js").write_text("export function helper() { return 1 }\n")
    (root / "b.js").write_text(
        "import { helper } from './a.js'\nfunction run() { return helper() }\n"
    )
    cfg = CodePrismConfig(languages=["javascript"], respect_gitignore=False)
    await ProjectIndexer(graph, storage, cfg).index(str(root))
    syms = {s.id: s.name for s in await storage.get_all_symbols()}
    assert ("run", "helper") in {
        (syms.get(e.from_id), syms.get(e.to_id))
        for e in await storage.get_all_edges()
        if e.kind == EdgeKind.CALLS
    }
