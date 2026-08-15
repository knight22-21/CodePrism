"""Tests for SecurityScanner and SecurityGate."""

from pathlib import Path

import pytest

from codeprism.security.gate import SecurityGate
from codeprism.security.scanner import SecurityScanner

FIXTURES = Path(__file__).parent / "fixtures" / "sample_security_issues"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ── SecurityScanner.scan_content ─────────────────────────────────────────────


def test_scan_clean_file_returns_pass():
    scanner = SecurityScanner()
    report = scanner.scan_content(_read("clean_example.py"))
    assert report.status == "PASS"
    assert report.issues == []


def test_scan_secrets_file_returns_block():
    scanner = SecurityScanner()
    report = scanner.scan_content(_read("secrets_example.py"))
    assert report.status == "BLOCK"
    assert report.is_blocked


def test_scan_injection_file_has_issues():
    scanner = SecurityScanner()
    report = scanner.scan_content(_read("injection_example.py"))
    assert len(report.issues) > 0


def test_scan_crypto_file_returns_warn_or_info():
    scanner = SecurityScanner()
    report = scanner.scan_content(_read("crypto_example.py"))
    assert report.status in {"WARN", "INFO"}
    assert len(report.issues) > 0


def test_scan_report_has_file_path():
    scanner = SecurityScanner()
    report = scanner.scan_content(_read("secrets_example.py"), file_path="secrets_example.py")
    assert report.file == "secrets_example.py"


def test_scan_to_dict_structure():
    scanner = SecurityScanner()
    report = scanner.scan_content(_read("secrets_example.py"))
    d = report.to_dict()
    assert "status" in d
    assert "issues" in d
    assert isinstance(d["issues"], list)
    assert "severity" in d["issues"][0]


def test_scan_secrets_only():
    scanner = SecurityScanner()
    report = scanner.scan_secrets_only(_read("secrets_example.py"))
    assert report.status == "BLOCK"
    detectors_used = {i.detector for i in report.issues}
    assert detectors_used == {"secrets"}


def test_scan_secrets_only_clean():
    scanner = SecurityScanner()
    report = scanner.scan_secrets_only(_read("clean_example.py"))
    assert report.status == "PASS"


# ── SecurityScanner.scan_diff ─────────────────────────────────────────────────


def test_diff_no_change_returns_pass():
    scanner = SecurityScanner()
    content = _read("secrets_example.py")
    report = scanner.scan_diff(content, content)
    # Same content → no *new* issues
    assert report.status == "PASS"


def test_diff_new_secret_is_flagged():
    scanner = SecurityScanner()
    original = _read("clean_example.py")
    proposed = original + '\nDATABASE_PASSWORD = "super_secret_123"\n'
    report = scanner.scan_diff(original, proposed)
    assert report.status == "BLOCK"
    assert any("password" in i.description.lower() for i in report.issues)


def test_diff_preexisting_issue_not_reflagged():
    scanner = SecurityScanner()
    original = 'password = "old_secret_123"\n'
    proposed = original + "\n# just a comment\n"
    report = scanner.scan_diff(original, proposed)
    # The password was already in original — not a new issue
    assert report.status == "PASS"


def test_diff_new_injection_is_flagged():
    scanner = SecurityScanner()
    original = _read("clean_example.py")
    proposed = original + '\nresult = eval(user_input)\n'
    report = scanner.scan_diff(original, proposed)
    assert len(report.issues) > 0
    assert any("eval" in i.description.lower() for i in report.issues)


def test_diff_adding_comment_no_issues():
    scanner = SecurityScanner()
    original = _read("clean_example.py")
    proposed = original + "\n# added comment\n"
    report = scanner.scan_diff(original, proposed)
    assert report.status == "PASS"


def test_diff_only_new_issues_reported():
    scanner = SecurityScanner()
    original = 'import hashlib\nreturn hashlib.md5(x).hexdigest()\n'
    proposed = original + 'password = "hunter2"\n'
    report = scanner.scan_diff(original, proposed)
    # md5 was in original → not re-reported; password is new → reported
    descriptions = [i.description for i in report.issues]
    assert any("password" in d.lower() for d in descriptions)
    assert not any("md5" in d.lower() for d in descriptions)


# ── SecurityGate ──────────────────────────────────────────────────────────────


async def test_gate_clean_write_is_pass(tmp_path):
    gate = SecurityGate()
    f = tmp_path / "module.py"
    f.write_text(_read("clean_example.py"), encoding="utf-8")
    report = await gate.check_write(str(f), _read("clean_example.py"))
    assert report.status == "PASS"
    assert not report.is_blocked


async def test_gate_blocks_new_secret(tmp_path):
    gate = SecurityGate()
    f = tmp_path / "module.py"
    f.write_text(_read("clean_example.py"), encoding="utf-8")
    proposed = _read("clean_example.py") + '\napi_key = "sk-secret1234567890abcdef12345678"\n'
    report = await gate.check_write(str(f), proposed)
    assert report.status == "BLOCK"
    assert report.is_blocked


async def test_gate_new_file_scans_full_content(tmp_path):
    gate = SecurityGate()
    new_file = str(tmp_path / "new.py")  # does not exist yet
    report = await gate.check_write(new_file, 'password = "secret123"\n')
    assert report.status == "BLOCK"


async def test_gate_check_content_clean():
    gate = SecurityGate()
    report = await gate.check_content(_read("clean_example.py"))
    assert report.status == "PASS"


async def test_gate_check_content_secrets():
    gate = SecurityGate()
    report = await gate.check_content(_read("secrets_example.py"))
    assert report.status == "BLOCK"


async def test_gate_warns_on_weak_crypto(tmp_path):
    gate = SecurityGate()
    f = tmp_path / "module.py"
    f.write_text("# empty\n", encoding="utf-8")
    proposed = "import hashlib\nreturn hashlib.md5(data).hexdigest()\n"
    report = await gate.check_write(str(f), proposed)
    assert report.status in {"WARN", "BLOCK"}


async def test_gate_has_warnings_property():
    gate = SecurityGate()
    report = await gate.check_content(_read("crypto_example.py"))
    assert report.has_warnings  # md5/sha1 are WARN


# ── Integration: session record_write uses scanner ────────────────────────────


async def test_session_write_with_secret_reports_block(tmp_path):
    """End-to-end: record_write surfaces the security status from the scanner."""
    import shutil
    from codeprism.core.config import CodePrismConfig
    from codeprism.core.graph import GraphEngine
    from codeprism.core.storage import StorageManager
    from codeprism.indexer.incremental_updater import IncrementalUpdater
    from codeprism.indexer.project_indexer import ProjectIndexer
    from codeprism.mcp.session import SessionManager

    PYTHON_FIXTURE = Path(__file__).parent / "fixtures" / "sample_python_project"
    proj = tmp_path / "project"
    shutil.copytree(PYTHON_FIXTURE, proj)

    db = StorageManager(tmp_path / "idx.db")
    await db.initialize()
    graph = GraphEngine()
    await ProjectIndexer(graph, db, CodePrismConfig(languages=["python"])).index(str(proj))

    updater = IncrementalUpdater(graph, db)
    manager = SessionManager(db, updater)

    fp = str(proj / "processor.py")
    before = Path(fp).read_text(encoding="utf-8")
    proposed = before + '\nSECRET_TOKEN = "sk-abcdefghijklmnopqrstuvwxyz1234"\n'

    report = await manager.record_write("test-sess", fp, before, proposed)
    assert report["status"] == "BLOCK"
    assert len(report["issues"]) > 0

    # CRITICAL: BLOCK must NOT write to disk — file should still have original content
    assert Path(fp).read_text(encoding="utf-8") == before

    await db.close()
