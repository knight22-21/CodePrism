"""Tests for the Python tree-sitter parser."""

from pathlib import Path

import pytest

from codeprism.core.models import EdgeKind, NodeKind
from codeprism.parser.python_parser import PythonParser

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_python_project"

# ── Inline source snippets ─────────────────────────────────────────────────────

SIMPLE = """\
import os
import hashlib as hl
from pathlib import Path
from typing import Optional, List

MY_CONST = 42

class Animal:
    \"\"\"Base animal class.\"\"\"

    def __init__(self, name: str):
        self.name = name

    def speak(self) -> str:
        return f"Hello, I'm {self.name}"

class Dog(Animal):
    \"\"\"A dog.\"\"\"

    def speak(self) -> str:
        base = Animal.speak(self)
        return "Woof! " + base

def greet(animal: Animal) -> str:
    return animal.speak()
"""

ASYNC_SRC = """\
async def fetch_data(url: str) -> dict:
    \"\"\"Fetch remote data.\"\"\"
    pass

async def process(items: list) -> list:
    result = fetch_data("http://example.com")
    return result
"""

DECORATED_SRC = """\
def decorator(fn):
    return fn

@decorator
def my_function():
    pass

class MyClass:
    @staticmethod
    def static_method():
        pass
"""


@pytest.fixture
def parser() -> PythonParser:
    return PythonParser()


# ── File record ────────────────────────────────────────────────────────────────

def test_file_record_language(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    assert result.file.language == "python"
    assert result.file.path == "/project/test.py"


def test_file_record_line_count(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    assert result.file.line_count == SIMPLE.count("\n") + 1


def test_file_record_checksum_is_stable(parser):
    r1 = parser.parse("/project/test.py", SIMPLE)
    r2 = parser.parse("/project/test.py", SIMPLE)
    assert r1.file.checksum == r2.file.checksum


# ── Imports ────────────────────────────────────────────────────────────────────

def test_extracts_plain_import(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    imports = {s.name for s in result.symbols if s.kind == NodeKind.IMPORT}
    assert "os" in imports


def test_extracts_aliased_import(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    imports = {s.name for s in result.symbols if s.kind == NodeKind.IMPORT}
    # `import hashlib as hl` → stored under alias "hl"
    assert "hl" in imports


def test_extracts_from_import_multi(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    imports = {s.name for s in result.symbols if s.kind == NodeKind.IMPORT}
    assert "Optional" in imports
    assert "List" in imports


def test_extracts_from_import_single(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    imports = {s.name for s in result.symbols if s.kind == NodeKind.IMPORT}
    assert "Path" in imports


# ── Classes ────────────────────────────────────────────────────────────────────

def test_extracts_class_names(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    classes = {s.name for s in result.symbols if s.kind == NodeKind.CLASS}
    assert "Animal" in classes
    assert "Dog" in classes


def test_class_line_numbers(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    animal = next(s for s in result.symbols if s.name == "Animal")
    assert animal.line_start is not None and animal.line_start > 0


def test_class_docstring(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    animal = next(s for s in result.symbols if s.name == "Animal")
    assert animal.docstring and "Base animal" in animal.docstring


def test_class_public_flag(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    animal = next(s for s in result.symbols if s.name == "Animal")
    assert animal.is_public is True


# ── Functions ──────────────────────────────────────────────────────────────────

def test_extracts_top_level_functions(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    funcs = {s.name for s in result.symbols if s.kind == NodeKind.FUNCTION}
    assert "greet" in funcs


def test_extracts_methods(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    funcs = {s.name for s in result.symbols if s.kind == NodeKind.FUNCTION}
    assert "__init__" in funcs
    assert "speak" in funcs


def test_function_signature_includes_params(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    greet = next(s for s in result.symbols if s.name == "greet")
    assert greet.signature and "animal" in greet.signature


def test_function_signature_includes_return_type(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    greet = next(s for s in result.symbols if s.name == "greet")
    assert greet.signature and "str" in greet.signature


def test_async_function_flag(parser):
    result = parser.parse("/project/async.py", ASYNC_SRC)
    fetch = next(s for s in result.symbols if s.name == "fetch_data")
    assert fetch.is_async is True


def test_non_async_function_flag(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    greet = next(s for s in result.symbols if s.name == "greet")
    assert greet.is_async is False


def test_decorated_function_extracted(parser):
    result = parser.parse("/project/dec.py", DECORATED_SRC)
    funcs = {s.name for s in result.symbols if s.kind == NodeKind.FUNCTION}
    assert "my_function" in funcs
    assert "static_method" in funcs


# ── Variables ──────────────────────────────────────────────────────────────────

def test_extracts_module_variable(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    variables = {s.name for s in result.symbols if s.kind == NodeKind.VARIABLE}
    assert "MY_CONST" in variables


# ── Edges — defines ────────────────────────────────────────────────────────────

def test_defines_edge_file_to_class(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    defines = [e for e in result.edges if e.kind == EdgeKind.DEFINES]
    class_ids = {s.id for s in result.symbols if s.kind == NodeKind.CLASS}
    defined_to_ids = {e.to_id for e in defines}
    assert class_ids.issubset(defined_to_ids), "All classes must have a DEFINES edge"


def test_defines_edge_class_to_method(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    defines = [e for e in result.edges if e.kind == EdgeKind.DEFINES]
    class_ids = {s.id for s in result.symbols if s.kind == NodeKind.CLASS}
    init_id = next(s.id for s in result.symbols if s.name == "__init__")
    # DEFINES from_id for __init__ should be a class
    method_defines = [e for e in defines if e.to_id == init_id]
    assert any(e.from_id in class_ids for e in method_defines)


def test_defines_edge_file_to_function(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    defines = [e for e in result.edges if e.kind == EdgeKind.DEFINES]
    greet_id = next(s.id for s in result.symbols if s.name == "greet")
    assert any(e.to_id == greet_id for e in defines)


# ── Edges — inherits ────────────────────────────────────────────────────────────

def test_intrafile_inherits_resolved(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    inherits = [e for e in result.edges if e.kind == EdgeKind.INHERITS]
    dog_id = next(s.id for s in result.symbols if s.name == "Dog")
    animal_id = next(s.id for s in result.symbols if s.name == "Animal")
    assert any(e.from_id == dog_id and e.to_id == animal_id for e in inherits)


def test_cross_file_inherits_stays_unresolved(parser):
    src = "class Child(ExternalBase):\n    pass\n"
    result = parser.parse("/project/child.py", src)
    inherits_edges = [e for e in result.edges if e.kind == EdgeKind.INHERITS]
    # ExternalBase not in this file → stays in unresolved_refs
    assert len(inherits_edges) == 0
    assert any(r.ref_name == "ExternalBase" for r in result.unresolved_refs)


# ── Edges — calls ──────────────────────────────────────────────────────────────

def test_intrafile_calls_resolved(parser):
    result = parser.parse("/project/test.py", SIMPLE)
    calls = [e for e in result.edges if e.kind == EdgeKind.CALLS]
    # greet calls speak
    greet_id = next(s.id for s in result.symbols if s.name == "greet")
    assert any(e.from_id == greet_id for e in calls)


def test_async_intrafile_call(parser):
    result = parser.parse("/project/async.py", ASYNC_SRC)
    calls = [e for e in result.edges if e.kind == EdgeKind.CALLS]
    process_id = next(s.id for s in result.symbols if s.name == "process")
    fetch_id = next(s.id for s in result.symbols if s.name == "fetch_data")
    assert any(e.from_id == process_id and e.to_id == fetch_id for e in calls)


def test_cross_file_call_stays_unresolved(parser):
    src = "def main():\n    external_lib.do_something()\n"
    result = parser.parse("/project/main.py", src)
    unresolved_calls = [r for r in result.unresolved_refs if r.kind == EdgeKind.CALLS]
    assert any(r.ref_name == "do_something" for r in unresolved_calls)


# ── Complexity ────────────────────────────────────────────────────────────────

def test_complexity_simple_function(parser):
    src = "def simple():\n    return 1\n"
    result = parser.parse("/project/f.py", src)
    func = next(s for s in result.symbols if s.name == "simple")
    assert func.complexity_score == 1.0


def test_complexity_branchy_function(parser):
    src = (
        "def branchy(x):\n"
        "    if x > 0:\n"
        "        for i in range(x):\n"
        "            if i % 2 == 0:\n"
        "                pass\n"
        "    return x\n"
    )
    result = parser.parse("/project/f.py", src)
    func = next(s for s in result.symbols if s.name == "branchy")
    assert func.complexity_score >= 3.0


# ── Fixture file ───────────────────────────────────────────────────────────────

def test_parse_fixture_file(parser):
    fixture = FIXTURE_DIR / "processor.py"
    content = fixture.read_text(encoding="utf-8")
    result = parser.parse(str(fixture), content)

    names = {s.name for s in result.symbols}
    assert "PaymentProcessor" in names
    assert "compute_checksum" in names
    assert "process" in names
    assert "_validate" in names

    # compute_checksum is called from within process
    calls = [e for e in result.edges if e.kind == EdgeKind.CALLS]
    process_id = next(s.id for s in result.symbols if s.name == "process")
    checksum_id = next(s.id for s in result.symbols if s.name == "compute_checksum")
    assert any(e.from_id == process_id and e.to_id == checksum_id for e in calls)
