"""Tests for individual security detectors."""

from pathlib import Path

from codeprism.security.detectors.crypto import WeakCryptoDetector
from codeprism.security.detectors.dependencies import DependenciesDetector
from codeprism.security.detectors.env_vars import EnvVarDetector
from codeprism.security.detectors.git_safety import GitSafetyDetector
from codeprism.security.detectors.injection import InjectionDetector
from codeprism.security.detectors.secrets import SecretsDetector

FIXTURES = Path(__file__).parent / "fixtures" / "sample_security_issues"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ── SecretsDetector ───────────────────────────────────────────────────────────


def test_secrets_detects_hardcoded_password():
    det = SecretsDetector()
    results = det.scan(_read("secrets_example.py"))
    descriptions = [r.description for r in results]
    assert any("password" in d.lower() for d in descriptions)


def test_secrets_detects_api_key():
    det = SecretsDetector()
    results = det.scan(_read("secrets_example.py"))
    descriptions = [r.description for r in results]
    assert any(
        "key" in d.lower() or "token" in d.lower() or "secret" in d.lower() for d in descriptions
    )


def test_secrets_all_are_block_or_warn_severity():
    det = SecretsDetector()
    results = det.scan(_read("secrets_example.py"))
    assert len(results) > 0
    for r in results:
        assert r.severity in {"BLOCK", "WARN"}
    # Hard patterns (passwords, API keys, tokens) must be BLOCK
    assert any(r.severity == "BLOCK" for r in results)


def test_secrets_reports_line_numbers():
    det = SecretsDetector()
    results = det.scan(_read("secrets_example.py"))
    for r in results:
        assert r.line_number is not None
        assert r.line_number > 0


def test_secrets_has_fix_suggestion():
    det = SecretsDetector()
    results = det.scan(_read("secrets_example.py"))
    for r in results:
        assert r.fix_suggestion is not None


def test_secrets_clean_file_no_findings():
    det = SecretsDetector()
    results = det.scan(_read("clean_example.py"))
    assert results == []


def test_secrets_hardcoded_password_literal():
    det = SecretsDetector()
    results = det.scan('password = "hunter2"')
    assert len(results) >= 1
    assert results[0].severity == "BLOCK"


def test_secrets_env_var_not_flagged():
    det = SecretsDetector()
    results = det.scan('password = os.environ.get("PASSWORD")')
    assert results == []


def test_secrets_detects_anthropic_key():
    det = SecretsDetector()
    # Construct at runtime to avoid triggering push-protection on the source file
    fake_key = "sk-ant-" + "api03-" + "a" * 32
    results = det.scan(f'key = "{fake_key}"')
    assert any("Anthropic" in r.description for r in results)


def test_secrets_detects_slack_token():
    det = SecretsDetector()
    # Construct at runtime to avoid triggering push-protection on the source file itself
    fake_tok = "xo" + "xb-111222333444-555666777888999-aAbBcCdDeEfFgGhH"
    results = det.scan(f'token = "{fake_tok}"')
    assert any("Slack" in r.description for r in results)


def test_secrets_detects_stripe_key():
    det = SecretsDetector()
    # Construct at runtime to avoid triggering push-protection on the source file itself
    fake_key = "sk" + "_live_" + "a" * 24
    results = det.scan(f'key = "{fake_key}"')
    assert any("Stripe" in r.description for r in results)


def test_secrets_detects_jwt():
    det = SecretsDetector()
    # Construct a syntactically valid JWT-shaped token at runtime
    fake_jwt = "eyJ" + "a" * 20 + "." + "b" * 20 + "." + "c" * 20
    results = det.scan(f'token = "{fake_jwt}"')
    assert any("JWT" in r.description for r in results)


# ── Entropy detection ─────────────────────────────────────────────────────────


def test_entropy_flags_high_entropy_string():
    from codeprism.security.detectors.secrets import _shannon_entropy

    # A random base64-like string has entropy > 4.5
    high_entropy = "aB3dEf7gHi9jKl2mNo4pQr6sT8uVwXyZ"
    assert _shannon_entropy(high_entropy) > 4.5


def test_entropy_does_not_flag_low_entropy_string():
    from codeprism.security.detectors.secrets import _shannon_entropy

    # Repetitive strings have low entropy
    assert _shannon_entropy("aaaaaaaaaaaaaaaaaaa") < 1.0


def test_entropy_detector_finds_secret_not_caught_by_patterns():
    det = SecretsDetector()
    # This looks like a random token but doesn't match any named pattern
    code = 'TOKEN = "aB3dEf7gHi9jKl2mNo4pQr6sT8uVwXyZ012345"'
    results = det.scan(code)
    assert any("entropy" in r.description.lower() for r in results)


def test_entropy_detector_skips_short_strings():
    det = SecretsDetector()
    # Short strings (< 20 chars) should not be flagged
    results = det.scan('x = "short_secret"')
    entropy_results = [r for r in results if "entropy" in r.description.lower()]
    assert entropy_results == []


def test_entropy_detector_does_not_double_flag_pattern_matches():
    det = SecretsDetector()
    # AKIA... is already caught by the AWS pattern — entropy pass should not add a second finding
    results = det.scan('KEY = "AKIAIOSFODNN7EXAMPLE_FAKE_KEY_12345"')
    entropy_results = [r for r in results if "entropy" in r.description.lower()]
    aws_results = [r for r in results if "AWS" in r.description]
    # Pattern match should be present; entropy result at same line should not be
    if aws_results:
        line = aws_results[0].line_number
        assert not any(r.line_number == line for r in entropy_results)


def test_entropy_empty_string_is_zero():
    from codeprism.security.detectors.secrets import _shannon_entropy

    assert _shannon_entropy("") == 0.0


# ── InjectionDetector ─────────────────────────────────────────────────────────


def test_injection_detects_eval():
    det = InjectionDetector()
    results = det.scan(_read("injection_example.py"))
    descriptions = [r.description for r in results]
    assert any("eval" in d.lower() for d in descriptions)


def test_injection_detects_sql_concat():
    det = InjectionDetector()
    results = det.scan(_read("injection_example.py"))
    descriptions = [r.description for r in results]
    assert any("sql" in d.lower() or "concatenation" in d.lower() for d in descriptions)


def test_injection_detects_sql_fstring():
    det = InjectionDetector()
    results = det.scan(_read("injection_example.py"))
    descriptions = [r.description for r in results]
    assert any("f-string" in d.lower() or "sql" in d.lower() for d in descriptions)


def test_injection_block_severity_for_sql():
    det = InjectionDetector()
    results = det.scan('cursor.execute(f"SELECT * FROM {table}")')
    block_results = [r for r in results if r.severity == "BLOCK"]
    assert len(block_results) >= 1


def test_injection_warn_for_shell_true():
    det = InjectionDetector()
    results = det.scan("subprocess.run(cmd, shell=True)")
    severities = [r.severity for r in results]
    assert "WARN" in severities


def test_injection_clean_file_no_sql_issues():
    det = InjectionDetector()
    results = det.scan(_read("clean_example.py"))
    block_results = [r for r in results if r.severity == "BLOCK"]
    assert block_results == []


def test_injection_parameterized_query_not_flagged():
    det = InjectionDetector()
    code = 'cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))'
    results = det.scan(code)
    assert results == []


# ── WeakCryptoDetector ────────────────────────────────────────────────────────


def test_crypto_detects_md5():
    det = WeakCryptoDetector()
    results = det.scan(_read("crypto_example.py"))
    descriptions = [r.description for r in results]
    assert any("md5" in d.lower() for d in descriptions)


def test_crypto_detects_sha1():
    det = WeakCryptoDetector()
    results = det.scan(_read("crypto_example.py"))
    descriptions = [r.description for r in results]
    assert any("sha-1" in d.lower() or "sha1" in d.lower() for d in descriptions)


def test_crypto_detects_random():
    det = WeakCryptoDetector()
    results = det.scan(_read("crypto_example.py"))
    descriptions = [r.description for r in results]
    assert any("random" in d.lower() for d in descriptions)


def test_crypto_md5_severity_warn():
    det = WeakCryptoDetector()
    results = det.scan("return hashlib.md5(data).hexdigest()")
    warn_results = [r for r in results if r.severity == "WARN"]
    assert len(warn_results) >= 1


def test_crypto_random_severity_info():
    det = WeakCryptoDetector()
    results = det.scan("x = random.randint(0, 100)")
    info_results = [r for r in results if r.severity == "INFO"]
    assert len(info_results) >= 1


def test_crypto_sha256_not_flagged():
    det = WeakCryptoDetector()
    results = det.scan(_read("clean_example.py"))
    assert results == []


# ── EnvVarDetector ────────────────────────────────────────────────────────────


def test_env_print_flagged():
    det = EnvVarDetector()
    results = det.scan('print(os.environ["SECRET"])')
    assert len(results) >= 1
    assert results[0].severity == "WARN"


def test_env_log_flagged():
    det = EnvVarDetector()
    results = det.scan('logging.info("key=%s", os.environ["KEY"])')
    assert len(results) >= 1


def test_env_safe_get_not_flagged():
    det = EnvVarDetector()
    results = det.scan('value = os.environ.get("KEY", "default")')
    assert results == []


def test_env_clean_file_no_findings():
    det = EnvVarDetector()
    results = det.scan(_read("clean_example.py"))
    assert results == []


# ── DependenciesDetector ──────────────────────────────────────────────────────


def test_deps_pickle_import_flagged():
    det = DependenciesDetector()
    results = det.scan("import pickle")
    assert len(results) >= 1
    assert results[0].severity == "WARN"


def test_deps_yaml_load_flagged():
    det = DependenciesDetector()
    results = det.scan("data = yaml.load(f)")
    block_results = [r for r in results if r.severity == "BLOCK"]
    assert len(block_results) >= 1


def test_deps_yaml_safe_load_not_flagged():
    det = DependenciesDetector()
    results = det.scan("data = yaml.safe_load(f)")
    assert results == []


def test_deps_clean_file_no_findings():
    det = DependenciesDetector()
    results = det.scan(_read("clean_example.py"))
    assert results == []


# ── GitSafetyDetector ─────────────────────────────────────────────────────────


def test_git_safety_bare_except_warn():
    det = GitSafetyDetector()
    results = det.scan("try:\n    risky()\nexcept:\n    pass\n")
    severities = [r.severity for r in results]
    assert "WARN" in severities


def test_git_safety_broad_exception_warn():
    det = GitSafetyDetector()
    results = det.scan("try:\n    risky()\nexcept Exception:\n    pass\n")
    severities = [r.severity for r in results]
    assert "WARN" in severities


def test_git_safety_silent_swallow_warn():
    det = GitSafetyDetector()
    results = det.scan("except ValueError: pass")
    # This doesn't match our patterns (specific exception) — no finding
    assert all(r.severity != "BLOCK" for r in results)


def test_git_safety_except_pass_inline_warn():
    det = GitSafetyDetector()
    results = det.scan("except Exception: pass")
    assert len(results) >= 1
    assert any(
        "swallow" in r.description.lower() or "suppress" in r.description.lower() for r in results
    )


def test_git_safety_pdb_warn():
    det = GitSafetyDetector()
    results = det.scan("import pdb\npdb.set_trace()\n")
    assert any(
        "pdb" in r.description.lower() or "breakpoint" in r.description.lower() for r in results
    )


def test_git_safety_breakpoint_warn():
    det = GitSafetyDetector()
    results = det.scan("breakpoint()\n")
    assert len(results) >= 1
    assert results[0].severity == "WARN"


def test_git_safety_clean_code_no_findings():
    det = GitSafetyDetector()
    results = det.scan("except ValueError as exc:\n    logger.exception(exc)\n")
    # Specific exception with logging — no broad-suppress patterns triggered
    block_or_warn = [r for r in results if r.severity in ("BLOCK", "WARN")]
    assert block_or_warn == []
