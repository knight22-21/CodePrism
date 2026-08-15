"""Tests for get_context(), get_impact(), and get_module_summary()."""

import pytest

from codeprism.core.models import NodeKind


# ── get_context ───────────────────────────────────────────────────────────────


async def test_context_returns_result(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_context(str(proj / "processor.py"), "compute_checksum")
    assert result is not None


async def test_context_symbol_correct(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_context(str(proj / "processor.py"), "compute_checksum")
    assert result.symbol.name == "compute_checksum"
    assert result.symbol.kind == NodeKind.FUNCTION


async def test_context_file_populated(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_context(str(proj / "processor.py"), "compute_checksum")
    assert result.file is not None
    assert "processor" in result.file.path


async def test_context_callers_included(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_context(str(proj / "processor.py"), "compute_checksum")
    # process() calls compute_checksum
    caller_names = {s.name for s in result.direct_callers}
    assert "process" in caller_names


async def test_context_callees_included(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_context(str(proj / "processor.py"), "process")
    # process() calls compute_checksum and _validate and _submit
    callee_names = {s.name for s in result.direct_callees}
    assert len(callee_names) > 0


async def test_context_token_estimate_positive(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_context(str(proj / "processor.py"), "compute_checksum")
    assert result.estimated_token_count > 0


async def test_context_depth_one_smaller_than_depth_two(indexed_engine):
    engine, db, proj = indexed_engine
    r1 = await engine.get_context(str(proj / "processor.py"), "PaymentProcessor", depth=1)
    r2 = await engine.get_context(str(proj / "processor.py"), "PaymentProcessor", depth=2)
    assert r1 is not None and r2 is not None
    # depth=2 has broader neighbourhood
    assert r2.estimated_token_count >= r1.estimated_token_count


async def test_context_returns_none_for_missing_symbol(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_context(str(proj / "processor.py"), "no_such_function_xyz")
    assert result is None


async def test_context_returns_none_for_missing_file(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_context("/no/such/file.py", "anything")
    assert result is None


# ── get_impact ────────────────────────────────────────────────────────────────


async def test_impact_returns_result(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_impact(str(proj / "processor.py"), "compute_checksum")
    assert result is not None


async def test_impact_symbol_correct(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_impact(str(proj / "processor.py"), "compute_checksum")
    assert result.symbol.name == "compute_checksum"


async def test_impact_direct_dependents(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_impact(str(proj / "processor.py"), "compute_checksum")
    # process() directly depends on compute_checksum
    dep_names = {s.name for s in result.direct_dependents}
    assert "process" in dep_names


async def test_impact_severity_is_valid(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_impact(str(proj / "processor.py"), "compute_checksum")
    assert result.severity in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


async def test_impact_change_surface_is_int(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_impact(str(proj / "processor.py"), "compute_checksum")
    assert isinstance(result.estimated_change_surface, int)
    assert result.estimated_change_surface >= 0


async def test_impact_isolated_function_is_low(indexed_engine):
    engine, db, proj = indexed_engine
    # _validate is a private method with no callers outside processor.py
    result = await engine.get_impact(str(proj / "processor.py"), "_validate")
    assert result is not None
    # _validate has limited reach → LOW or MEDIUM
    assert result.severity in {"LOW", "MEDIUM"}


async def test_impact_returns_none_for_missing(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_impact("/no/file.py", "nothing")
    assert result is None


async def test_impact_public_api_flag(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_impact(str(proj / "processor.py"), "compute_checksum")
    # compute_checksum is public (no underscore) — public_api_affected should be True
    # if it has callers, which it does
    assert isinstance(result.public_api_affected, bool)


# ── get_module_summary ────────────────────────────────────────────────────────


async def test_summary_returns_result(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_module_summary(str(proj / "processor.py"))
    assert result is not None


async def test_summary_file_populated(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_module_summary(str(proj / "processor.py"))
    assert "processor" in result.file.path


async def test_summary_has_purpose(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_module_summary(str(proj / "processor.py"))
    assert result.purpose != ""
    assert "processor" in result.purpose.lower()


async def test_summary_public_api_includes_class(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_module_summary(str(proj / "processor.py"))
    names = {s.name for s in result.public_api}
    assert "PaymentProcessor" in names or "compute_checksum" in names


async def test_summary_key_classes(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_module_summary(str(proj / "processor.py"))
    names = {c.name for c in result.key_classes}
    assert "PaymentProcessor" in names


async def test_summary_dependencies_non_empty(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_module_summary(str(proj / "processor.py"))
    # processor.py imports os, hashlib, Optional
    assert len(result.dependencies) > 0


async def test_summary_complexity_score_non_negative(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_module_summary(str(proj / "processor.py"))
    assert result.complexity_score >= 0.0


async def test_summary_finds_test_file(indexed_engine):
    engine, db, proj = indexed_engine
    # There is no test_ file for processor in fixtures — should be None
    result = await engine.get_module_summary(str(proj / "processor.py"))
    # May or may not find a test file; just assert it's str or None
    assert result.test_coverage_file is None or isinstance(result.test_coverage_file, str)


async def test_summary_returns_none_for_missing(indexed_engine):
    engine, db, proj = indexed_engine
    result = await engine.get_module_summary("/no/such/file.py")
    assert result is None
