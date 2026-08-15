"""Tests for the JavaScript / TypeScript parser."""

from pathlib import Path

import pytest

from codeprism.core.models import EdgeKind, NodeKind
from codeprism.parser.javascript_parser import JavaScriptParser

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_js_project"

JS_SRC = """\
import { computeHash, formatAmount } from './utils.js';

class PaymentService extends BaseService {
  constructor(config) {
    super(config);
    this.retries = 3;
  }

  async processPayment(amount) {
    if (amount <= 0) return false;
    const hash = computeHash(amount.toString());
    return this._submit(amount, hash);
  }

  _submit(amount, hash) {
    return true;
  }
}

function createService(config) {
  return new PaymentService(config);
}

const DEFAULT_TIMEOUT = 5000;
const helper = (x) => x * 2;
"""

TS_SRC = """\
export interface HashOptions {
  algorithm: string;
  encoding: string;
}

export type HashResult = {
  value: string;
};

export function computeHash(data: string, options?: HashOptions): string {
  return data.length.toString();
}

export function formatAmount(amount: number, currency: string = "USD"): string {
  return `${currency} ${amount.toFixed(2)}`;
}

export const DEFAULT_OPTIONS: HashOptions = {
  algorithm: "sha256",
  encoding: "hex",
};
"""


@pytest.fixture
def parser() -> JavaScriptParser:
    return JavaScriptParser()


# ── File record ────────────────────────────────────────────────────────────────

def test_js_file_language(parser):
    result = parser.parse("/project/service.js", JS_SRC)
    assert result.file.language == "javascript"


def test_ts_file_language(parser):
    result = parser.parse("/project/utils.ts", TS_SRC)
    assert result.file.language == "typescript"


def test_file_line_count(parser):
    result = parser.parse("/project/service.js", JS_SRC)
    assert result.file.line_count == JS_SRC.count("\n") + 1


# ── Imports ────────────────────────────────────────────────────────────────────

def test_extracts_named_imports(parser):
    result = parser.parse("/project/service.js", JS_SRC)
    imports = {s.name for s in result.symbols if s.kind == NodeKind.IMPORT}
    assert "computeHash" in imports
    assert "formatAmount" in imports


# ── Classes ────────────────────────────────────────────────────────────────────

def test_extracts_class(parser):
    result = parser.parse("/project/service.js", JS_SRC)
    classes = {s.name for s in result.symbols if s.kind == NodeKind.CLASS}
    assert "PaymentService" in classes


def test_class_line_numbers(parser):
    result = parser.parse("/project/service.js", JS_SRC)
    cls = next(s for s in result.symbols if s.name == "PaymentService")
    assert cls.line_start is not None and cls.line_start > 0


# ── Methods ────────────────────────────────────────────────────────────────────

def test_extracts_methods(parser):
    result = parser.parse("/project/service.js", JS_SRC)
    funcs = {s.name for s in result.symbols if s.kind == NodeKind.FUNCTION}
    assert "processPayment" in funcs
    assert "_submit" in funcs
    assert "constructor" in funcs


def test_async_method_flag(parser):
    result = parser.parse("/project/service.js", JS_SRC)
    method = next(s for s in result.symbols if s.name == "processPayment")
    assert method.is_async is True


def test_sync_method_flag(parser):
    result = parser.parse("/project/service.js", JS_SRC)
    method = next(s for s in result.symbols if s.name == "_submit")
    assert method.is_async is False


# ── Functions ──────────────────────────────────────────────────────────────────

def test_extracts_function_declaration(parser):
    result = parser.parse("/project/service.js", JS_SRC)
    funcs = {s.name for s in result.symbols if s.kind == NodeKind.FUNCTION}
    assert "createService" in funcs


def test_extracts_arrow_function(parser):
    result = parser.parse("/project/service.js", JS_SRC)
    funcs = {s.name for s in result.symbols if s.kind == NodeKind.FUNCTION}
    assert "helper" in funcs


# ── Variables ──────────────────────────────────────────────────────────────────

def test_extracts_const_variable(parser):
    result = parser.parse("/project/service.js", JS_SRC)
    vars_ = {s.name for s in result.symbols if s.kind == NodeKind.VARIABLE}
    assert "DEFAULT_TIMEOUT" in vars_


# ── Edges — defines ────────────────────────────────────────────────────────────

def test_defines_edge_file_to_class(parser):
    result = parser.parse("/project/service.js", JS_SRC)
    defines = [e for e in result.edges if e.kind == EdgeKind.DEFINES]
    class_ids = {s.id for s in result.symbols if s.kind == NodeKind.CLASS}
    defined_ids = {e.to_id for e in defines}
    assert class_ids.issubset(defined_ids)


def test_defines_edge_class_to_method(parser):
    result = parser.parse("/project/service.js", JS_SRC)
    defines = [e for e in result.edges if e.kind == EdgeKind.DEFINES]
    cls_id = next(s.id for s in result.symbols if s.name == "PaymentService")
    method_id = next(s.id for s in result.symbols if s.name == "processPayment")
    assert any(e.from_id == cls_id and e.to_id == method_id for e in defines)


# ── Edges — inherits ───────────────────────────────────────────────────────────

def test_inherits_stays_unresolved_for_cross_file_base(parser):
    result = parser.parse("/project/service.js", JS_SRC)
    inherits_edges = [e for e in result.edges if e.kind == EdgeKind.INHERITS]
    # BaseService is not defined in this file
    assert len(inherits_edges) == 0
    assert any(r.ref_name == "BaseService" for r in result.unresolved_refs)


# ── Edges — calls ──────────────────────────────────────────────────────────────

def test_intrafile_call_not_resolved_for_external(parser):
    result = parser.parse("/project/service.js", JS_SRC)
    # computeHash is an IMPORT, not a defined function — stays unresolved
    calls = [e for e in result.edges if e.kind == EdgeKind.CALLS]
    method_id = next(s.id for s in result.symbols if s.name == "processPayment")
    # from processPayment there should be call refs
    method_calls = [e for e in calls if e.from_id == method_id]
    unresolved_from_method = [r for r in result.unresolved_refs if r.from_id == method_id]
    assert len(method_calls) + len(unresolved_from_method) > 0


# ── TypeScript ─────────────────────────────────────────────────────────────────

def test_ts_extracts_interface(parser):
    result = parser.parse("/project/utils.ts", TS_SRC)
    types = {s.name for s in result.symbols if s.kind == NodeKind.TYPE}
    assert "HashOptions" in types


def test_ts_extracts_type_alias(parser):
    result = parser.parse("/project/utils.ts", TS_SRC)
    types = {s.name for s in result.symbols if s.kind == NodeKind.TYPE}
    assert "HashResult" in types


def test_ts_extracts_functions(parser):
    result = parser.parse("/project/utils.ts", TS_SRC)
    funcs = {s.name for s in result.symbols if s.kind == NodeKind.FUNCTION}
    assert "computeHash" in funcs
    assert "formatAmount" in funcs


def test_ts_defines_edges_for_exported_functions(parser):
    result = parser.parse("/project/utils.ts", TS_SRC)
    defines = [e for e in result.edges if e.kind == EdgeKind.DEFINES]
    func_ids = {s.id for s in result.symbols if s.kind == NodeKind.FUNCTION}
    defined_ids = {e.to_id for e in defines}
    assert func_ids.issubset(defined_ids)


# ── Fixture files ──────────────────────────────────────────────────────────────

def test_parse_js_fixture(parser):
    fixture = FIXTURE_DIR / "service.js"
    content = fixture.read_text(encoding="utf-8")
    result = parser.parse(str(fixture), content)
    names = {s.name for s in result.symbols}
    assert "PaymentService" in names
    assert "createService" in names
    assert "DEFAULT_TIMEOUT" in names


def test_parse_ts_fixture(parser):
    fixture = FIXTURE_DIR / "utils.ts"
    content = fixture.read_text(encoding="utf-8")
    result = parser.parse(str(fixture), content)
    names = {s.name for s in result.symbols}
    assert "computeHash" in names
    assert "HashOptions" in names
    assert "DEFAULT_OPTIONS" in names
