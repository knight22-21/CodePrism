"""Language coverage: every supported language is indexed and watched by default."""

import pytest

from codeprism.core.config import CodePrismConfig
from codeprism.core.languages import (
    ALL_EXTENSIONS,
    LANGUAGE_EXTENSIONS,
    SUPPORTED_LANGUAGES,
    extensions_for,
    normalize_language,
)
from codeprism.indexer.project_indexer import ProjectIndexer
from codeprism.indexer.watcher import _WATCH_EXTENSIONS
from codeprism.parser.generic_parser import GenericParser
from codeprism.parser.registry import ParserRegistry

SAMPLES = {
    "Main.java": "public class Main { public void run() {} }\n",
    "util.c": "int add(int a, int b) { return a + b; }\n",
    "graph.cpp": "class Node { public: void visit() {} };\n",
    "task.rb": "class Task\n  def run\n  end\nend\n",
    "svc.php": "<?php\nfunction handle() { return 1; }\n",
    "lib.rs": "fn compute() -> i32 { 1 }\n",
}


@pytest.mark.parametrize("ext", sorted(ALL_EXTENSIONS))
def test_every_listed_extension_has_a_real_parser(ext):
    assert not isinstance(ParserRegistry().get(f"file{ext}"), GenericParser)


def test_default_config_covers_all_supported_languages():
    assert set(CodePrismConfig().languages) == set(SUPPORTED_LANGUAGES)
    assert len(SUPPORTED_LANGUAGES) == 10


def test_watcher_reacts_to_every_supported_extension():
    assert _WATCH_EXTENSIONS == ALL_EXTENSIONS
    for ext in (".rs", ".java", ".c", ".cpp", ".rb", ".php"):
        assert ext in _WATCH_EXTENSIONS


def test_aliases_and_unknown_languages():
    assert normalize_language("C++") == "cpp"
    assert extensions_for(["c++"]) == LANGUAGE_EXTENSIONS["cpp"]
    # A typo must never silently index zero files
    assert extensions_for(["pyhton"]) == ALL_EXTENSIONS


async def test_default_index_parses_newer_languages(storage, graph, tmp_path):
    for name, content in SAMPLES.items():
        (tmp_path / name).write_text(content)

    result = await ProjectIndexer(graph, storage, CodePrismConfig()).index(str(tmp_path))

    assert result.errors == []
    indexed = {f.path.replace("\\", "/").rsplit("/", 1)[-1] for f in await storage.get_all_files()}
    assert indexed == set(SAMPLES)
    names = {s.name for s in await storage.get_all_symbols()}
    for expected in ("Main", "add", "Node", "Task", "handle", "compute"):
        assert expected in names
