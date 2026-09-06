"""Property-based tests using Hypothesis.

These tests assert *invariants* that must hold for any valid input,
not just specific examples. They complement the example-based tests
with adversarial, randomly-generated inputs.
"""

from __future__ import annotations

import string

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from codeprism.core.graph import GraphEngine
from codeprism.core.models import EdgeKind, NodeKind
from codeprism.security.detectors.secrets import SecretsDetector
from codeprism.security.detectors.injection import InjectionDetector
from codeprism.security.detectors.crypto import WeakCryptoDetector
from codeprism.security.scanner import SecurityScanner
from codeprism.query.engine import SearchMatch

from tests.conftest import make_edge, make_file, make_symbol


# ── Strategies ────────────────────────────────────────────────────────────────

# Safe printable text that won't accidentally contain a secret pattern
safe_text = st.text(
    alphabet=string.ascii_letters + string.digits + " _.()\n",
    min_size=0,
    max_size=500,
)

identifier = st.text(
    alphabet=string.ascii_lowercase + "_",
    min_size=1,
    max_size=40,
).filter(lambda s: s[0].isalpha())

node_kind = st.sampled_from([
    NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.VARIABLE,
])

edge_kind = st.sampled_from(list(EdgeKind))


# ── SecurityScanner invariants ────────────────────────────────────────────────


@given(content=safe_text)
@settings(max_examples=200)
def test_scanner_status_is_always_valid_enum(content):
    """scan_content always returns PASS, WARN, or BLOCK — never anything else."""
    scanner = SecurityScanner()
    report = scanner.scan_content(content, "test.py")
    assert report.status in {"PASS", "WARN", "BLOCK"}


@given(content=safe_text)
@settings(max_examples=200)
def test_scanner_block_iff_block_issue_present(content):
    """status is BLOCK iff at least one issue has severity BLOCK."""
    scanner = SecurityScanner()
    report = scanner.scan_content(content, "test.py")
    has_block_issue = any(i.severity == "BLOCK" for i in report.issues)
    assert report.is_blocked == has_block_issue


@given(content=safe_text)
@settings(max_examples=200)
def test_scanner_issues_all_have_line_numbers(content):
    """Every reported issue carries a positive line number."""
    scanner = SecurityScanner()
    report = scanner.scan_content(content, "test.py")
    for issue in report.issues:
        assert issue.line_number is not None
        assert issue.line_number >= 1


@given(content=safe_text)
@settings(max_examples=200)
def test_scanner_issues_severity_subset(content):
    """Every issue severity is one of the three valid values."""
    scanner = SecurityScanner()
    report = scanner.scan_content(content, "test.py")
    for issue in report.issues:
        assert issue.severity in {"BLOCK", "WARN", "INFO"}


@given(original=safe_text, proposed=safe_text)
@settings(max_examples=100)
def test_scan_diff_status_is_valid(original, proposed):
    """scan_diff always returns a valid status regardless of inputs."""
    scanner = SecurityScanner()
    report = scanner.scan_diff(original, proposed, "test.py")
    assert report.status in {"PASS", "WARN", "BLOCK"}


@given(content=safe_text)
@settings(max_examples=100)
def test_scan_diff_identical_is_always_pass(content):
    """Scanning identical original and proposed must never produce new findings."""
    scanner = SecurityScanner()
    report = scanner.scan_diff(content, content, "test.py")
    assert report.status == "PASS"
    assert report.issues == []


# ── SecretsDetector invariants ────────────────────────────────────────────────


@given(
    key=st.text(alphabet=string.ascii_letters + string.digits, min_size=8, max_size=40),
)
@settings(max_examples=150)
def test_secrets_detects_hardcoded_api_key(key):
    """Any content matching api_key = '...' with ≥8-char value must fire."""
    content = f'api_key = "{key}"\n'
    det = SecretsDetector()
    results = det.scan(content)
    assert len(results) >= 1, f"Expected a finding for: {content!r}"
    assert all(r.severity == "BLOCK" for r in results)


@given(
    pw=st.text(alphabet=string.ascii_letters + string.digits, min_size=4, max_size=30),
)
@settings(max_examples=150)
def test_secrets_detects_hardcoded_password(pw):
    """Any content matching password = '...' with ≥4-char value must fire."""
    content = f'password = "{pw}"\n'
    det = SecretsDetector()
    results = det.scan(content)
    assert len(results) >= 1, f"Expected a finding for: {content!r}"


@given(content=safe_text)
@settings(max_examples=200)
def test_secrets_all_results_have_fix_suggestion(content):
    """Every secret finding must carry a fix_suggestion (non-empty string)."""
    det = SecretsDetector()
    for r in det.scan(content):
        assert r.fix_suggestion is not None
        assert len(r.fix_suggestion) > 0


# ── InjectionDetector invariants ──────────────────────────────────────────────


@given(
    query=st.text(
        alphabet=string.ascii_letters + string.digits + " _",
        min_size=1, max_size=40,
    )
)
@settings(max_examples=150)
def test_injection_detects_fstring_sql(query):
    """f-string SQL concatenation must always be flagged."""
    content = f'cursor.execute(f"SELECT * FROM users WHERE name = \'{{{query}}}\'")\n'
    det = InjectionDetector()
    results = det.scan(content)
    assert len(results) >= 1, f"Expected SQL injection finding for: {content!r}"


@given(content=safe_text)
@settings(max_examples=200)
def test_injection_results_severity_valid(content):
    """All injection findings carry BLOCK or WARN severity."""
    det = InjectionDetector()
    for r in det.scan(content):
        assert r.severity in {"BLOCK", "WARN"}


# ── WeakCryptoDetector invariants ─────────────────────────────────────────────


@given(content=safe_text)
@settings(max_examples=200)
def test_crypto_results_severity_is_warn(content):
    """Weak crypto findings are WARN, never BLOCK (they're advisory)."""
    det = WeakCryptoDetector()
    for r in det.scan(content):
        assert r.severity == "WARN"


# ── GraphEngine invariants ────────────────────────────────────────────────────


@given(names=st.lists(identifier, min_size=1, max_size=20, unique=True))
@settings(max_examples=100)
def test_graph_node_count_matches_added(names):
    """Adding N uniquely-named symbols produces exactly N retrievable nodes."""
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    syms = [make_symbol(name, file=f) for name in names]
    for sym in syms:
        g.add_symbol(sym)
    for sym in syms:
        assert g.has_node(sym.id)
        assert g.get_symbol(sym.id).name == sym.name


@given(names=st.lists(identifier, min_size=2, max_size=10, unique=True))
@settings(max_examples=100)
def test_graph_remove_symbol_makes_it_unreachable(names):
    """After removal, has_node and get_symbol must both return falsy."""
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    syms = [make_symbol(name, file=f) for name in names]
    for sym in syms:
        g.add_symbol(sym)
    target = syms[0]
    g.remove_symbol(target.id)
    assert not g.has_node(target.id)
    assert g.get_symbol(target.id) is None
    # All others still intact
    for sym in syms[1:]:
        assert g.has_node(sym.id)


@given(
    a_name=identifier,
    b_name=identifier,
    kind=edge_kind,
)
@settings(max_examples=100)
def test_graph_edge_survives_roundtrip(a_name, b_name, kind):
    """An edge added to the graph is retrievable via get_edges_from."""
    assume(a_name != b_name)
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    a = make_symbol(a_name, file=f)
    b = make_symbol(b_name, file=f)
    g.add_symbol(a)
    g.add_symbol(b)
    e = make_edge(a, b, kind=kind)
    g.add_edge(e)
    edges = g.get_edges_from(a.id, kind=kind)
    assert any(ed.id == e.id for ed in edges)


@given(
    a_name=identifier,
    b_name=identifier,
)
@settings(max_examples=100)
def test_graph_callers_callees_symmetry(a_name, b_name):
    """If A calls B: A is in callees(A) and B is in callers(B)."""
    assume(a_name != b_name)
    g = GraphEngine()
    f = make_file()
    g.add_file(f)
    a = make_symbol(a_name, file=f)
    b = make_symbol(b_name, file=f)
    g.add_symbol(a)
    g.add_symbol(b)
    e = make_edge(a, b, kind=EdgeKind.CALLS)
    g.add_edge(e)
    callees_of_a = [s.id for s in g.get_callees(a.id)]
    callers_of_b = [s.id for s in g.get_callers(b.id)]
    assert b.id in callees_of_a
    assert a.id in callers_of_b


# ── SearchMatch score invariant ───────────────────────────────────────────────


@given(
    score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50)
def test_search_match_score_in_unit_interval(score):
    """SearchMatch.score from semantic search must always be in [0, 1]."""
    f = make_file()
    sym = make_symbol("example", file=f)
    match = SearchMatch(symbol=sym, file_path=f.path, score=score)
    assert 0.0 <= match.score <= 1.0
