"""Tests for CVE vulnerability checker and requirements parsing."""

from __future__ import annotations

import io
import json
import urllib.error
from unittest import mock

from codeprism.security import cve


def mock_check_package(pkg: str, version: str = "") -> cve.CVEResult:
    # A mock that records package name and version
    # Set severity to "HIGH" so it gets included in results list
    return cve.CVEResult(package=pkg, version=version, cve_ids=[], severity="HIGH", summary="")


def test_check_requirements_parsing():
    reqs = (
        "requests==2.32.3\n"
        "flask>2.0\n"
        "numpy; python_version<'3.9'\n"
        "click<9\n"
        "baz >= 1.0\n"
        "requests[security]>=2\n"
        "pkg # comment\n"
        "   \n"  # blank line
        "-r other.txt\n"  # should be skipped
        "http://example.com/pkg.zip\n"  # should be skipped
        "django-cors-headers\n"
        "Django==3.0\n"
    )

    with mock.patch(
        "codeprism.security.cve.check_package", side_effect=mock_check_package
    ) as mock_check:
        results = cve.check_requirements(reqs)

        # Verify exactly the expected packages were looked up
        seen_packages = [r.package for r in results]
        expected_packages = [
            "requests",
            "flask",
            "numpy",
            "click",
            "baz",
            "requests",
            "pkg",
            "django-cors-headers",
            "Django",
        ]

        assert seen_packages == expected_packages
        assert mock_check.call_count == len(expected_packages)

        # Verify exact package and version pairs
        seen_pairs = [(r.package, r.version) for r in results]
        expected_pairs = [
            ("requests", "2.32.3"),
            ("flask", ""),
            ("numpy", ""),
            ("click", ""),
            ("baz", ""),
            ("requests", ""),
            ("pkg", ""),
            ("django-cors-headers", ""),
            ("Django", "3.0"),
        ]
        assert seen_pairs == expected_pairs


def test_check_requirements_skips_valid_packages():
    # If check_package returns PASS or UNKNOWN, it should be filtered out
    def mock_pass(pkg: str, version: str = ""):
        return cve.CVEResult(package=pkg, version=version, severity="PASS")

    with mock.patch("codeprism.security.cve.check_package", side_effect=mock_pass):
        results = cve.check_requirements("flask")
        assert len(results) == 0


# --- Phase 3 Regression Tests ---


def test_check_package_versioned_payload():
    """Assert OSV request contains 'version' when a non-empty version is provided."""
    mock_response = io.BytesIO(b'{"vulns": []}')

    with mock.patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        result = cve.check_package("requests", "2.32.3")

        assert mock_urlopen.call_count == 1
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))

        assert payload == {
            "version": "2.32.3",
            "package": {
                "name": "requests",
                "ecosystem": "PyPI",
            },
        }
        assert result.package == "requests"
        assert result.version == "2.32.3"
        assert result.severity == "PASS"


def test_check_package_unversioned_payload():
    """Assert OSV request omits 'version' when version is empty or omitted."""
    mock_response = io.BytesIO(b'{"vulns": []}')

    with mock.patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        result_default = cve.check_package("requests")
        req_default = mock_urlopen.call_args[0][0]
        payload_default = json.loads(req_default.data.decode("utf-8"))

        assert "version" not in payload_default
        assert payload_default == {
            "package": {
                "name": "requests",
                "ecosystem": "PyPI",
            },
        }
        assert result_default.package == "requests"
        assert result_default.version == ""

    mock_response2 = io.BytesIO(b'{"vulns": []}')
    with mock.patch("urllib.request.urlopen", return_value=mock_response2) as mock_urlopen2:
        result_empty = cve.check_package("requests", "")
        req_empty = mock_urlopen2.call_args[0][0]
        payload_empty = json.loads(req_empty.data.decode("utf-8"))

        assert "version" not in payload_empty
        assert result_empty.package == "requests"
        assert result_empty.version == ""


def test_check_package_strips_whitespace():
    """Assert leading/trailing whitespace in package name and version is trimmed."""
    mock_response = io.BytesIO(b'{"vulns": []}')

    with mock.patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        result = cve.check_package("  requests  ", "  2.32.3  ")
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))

        assert payload["package"]["name"] == "requests"
        assert payload["version"] == "2.32.3"
        assert result.package == "requests"
        assert result.version == "2.32.3"


def test_check_package_network_error_fallback():
    """Assert network errors fall back to UNKNOWN and preserve package and version."""
    with mock.patch(
        "urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")
    ):
        result = cve.check_package("requests", "2.32.3")
        assert result.package == "requests"
        assert result.version == "2.32.3"
        assert result.severity == "UNKNOWN"
        assert result.cve_ids == []


def test_check_package_reports_vulnerabilities():
    """Assert vulnerabilities returned by OSV are parsed and severity ranked."""
    osv_data = {
        "vulns": [
            {
                "aliases": ["CVE-2023-32681", "GHSA-j8r2-6x86-q33q"],
                "database_specific": {"severity": "MEDIUM"},
            },
            {
                "aliases": ["CVE-2024-35195"],
                "database_specific": {"severity": "HIGH"},
            },
        ]
    }
    mock_response = io.BytesIO(json.dumps(osv_data).encode("utf-8"))

    with mock.patch("urllib.request.urlopen", return_value=mock_response):
        result = cve.check_package("requests", "2.31.0")
        assert result.package == "requests"
        assert result.version == "2.31.0"
        assert result.severity == "HIGH"
        assert "CVE-2023-32681" in result.cve_ids
        assert "CVE-2024-35195" in result.cve_ids
        assert result.summary == "2 known vulnerabilities for requests"


def test_check_requirements_exact_equal_and_arbitrary_equal():
    """Assert == and === exact pins extract package and version."""
    calls: list[tuple[str, str]] = []

    def record_call(pkg: str, version: str = "") -> cve.CVEResult:
        calls.append((pkg, version))
        return cve.CVEResult(package=pkg, version=version, severity="HIGH")

    reqs = "requests==2.32.3\nDjango===4.2.0\npkg == 1.0.0\n"
    with mock.patch("codeprism.security.cve.check_package", side_effect=record_call):
        results = cve.check_requirements(reqs)

        assert calls == [
            ("requests", "2.32.3"),
            ("Django", "4.2.0"),
            ("pkg", "1.0.0"),
        ]
        assert len(results) == 3


def test_check_requirements_extras_stripped():
    """Assert extras brackets are stripped from package name while exact version is preserved."""
    calls: list[tuple[str, str]] = []

    def record_call(pkg: str, version: str = "") -> cve.CVEResult:
        calls.append((pkg, version))
        return cve.CVEResult(package=pkg, version=version, severity="HIGH")

    reqs = (
        "urllib3[socks]==2.0.7\n"
        "requests[security,socks] == 2.31.0\n"
        "requests[security, tests] == 2.32.3\n"
        "fastapi[all]===0.110.0\n"
    )
    with mock.patch("codeprism.security.cve.check_package", side_effect=record_call):
        cve.check_requirements(reqs)

        assert calls == [
            ("urllib3", "2.0.7"),
            ("requests", "2.31.0"),
            ("requests", "2.32.3"),
            ("fastapi", "0.110.0"),
        ]


def test_check_requirements_inline_comments_and_markers():
    """Assert inline comments and environment markers do not corrupt package or version."""
    calls: list[tuple[str, str]] = []

    def record_call(pkg: str, version: str = "") -> cve.CVEResult:
        calls.append((pkg, version))
        return cve.CVEResult(package=pkg, version=version, severity="HIGH")

    reqs = (
        "numpy==1.26.4 # critical pinned version\n"
        "pandas==2.2.1; python_version >= '3.10'\n"
        "scipy==1.11.0; sys_platform == 'linux' # for production linux\n"
        "uvicorn[standard]==0.29.0 ; os_name == 'posix' # async server\n"
    )
    with mock.patch("codeprism.security.cve.check_package", side_effect=record_call):
        cve.check_requirements(reqs)

        assert calls == [
            ("numpy", "1.26.4"),
            ("pandas", "2.2.1"),
            ("scipy", "1.11.0"),
            ("uvicorn", "0.29.0"),
        ]


def test_check_requirements_ranged_and_unpinned_remain_unversioned():
    """Assert non-exact specifiers (>, >=, <, <=, ~=, !=) and unpinned packages pass empty version."""
    calls: list[tuple[str, str]] = []

    def record_call(pkg: str, version: str = "") -> cve.CVEResult:
        calls.append((pkg, version))
        return cve.CVEResult(package=pkg, version=version, severity="HIGH")

    reqs = (
        "flask>2.0\n"
        "click>=8.0.0\n"
        "click>=8.0.0,<9.0.0\n"
        "pytest~=7.4.0\n"
        "black!=23.1.0\n"
        "coverage<=7.0\n"
        "six<2.0\n"
        "requests[security]>=2.0\n"
        "tqdm\n"
        "django-cors-headers # comment\n"
    )
    with mock.patch("codeprism.security.cve.check_package", side_effect=record_call):
        cve.check_requirements(reqs)

        expected = [
            ("flask", ""),
            ("click", ""),
            ("click", ""),
            ("pytest", ""),
            ("black", ""),
            ("coverage", ""),
            ("six", ""),
            ("requests", ""),
            ("tqdm", ""),
            ("django-cors-headers", ""),
        ]
        assert calls == expected


def test_check_requirements_wildcard_equality_remains_unversioned():
    """Assert wildcard equality pins (==2.32.*, ===2.0.*) do not get treated as exact versions."""
    calls: list[tuple[str, str]] = []

    def record_call(pkg: str, version: str = "") -> cve.CVEResult:
        calls.append((pkg, version))
        return cve.CVEResult(package=pkg, version=version, severity="HIGH")

    reqs = (
        "requests==2.32.*\n"
        "urllib3===2.0.*\n"
        "pkg == 1.2.* # wildcard with comment\n"
        "pkg[extra]==3.* ; python_version >= '3.8'\n"
    )
    with mock.patch("codeprism.security.cve.check_package", side_effect=record_call):
        cve.check_requirements(reqs)

        assert calls == [
            ("requests", ""),
            ("urllib3", ""),
            ("pkg", ""),
            ("pkg", ""),
        ]


def test_check_requirements_skips_unsupported_lines():
    """Assert comments, flags, editable installs, URLs, and VCS references are safely skipped."""
    calls: list[tuple[str, str]] = []

    def record_call(pkg: str, version: str = "") -> cve.CVEResult:
        calls.append((pkg, version))
        return cve.CVEResult(package=pkg, version=version, severity="HIGH")

    reqs = (
        "# full line comment\n"
        "   # indented comment\n"
        "\n"
        "   \n"
        "-r requirements-dev.txt\n"
        "-e .\n"
        "-f /path/to/wheels\n"
        "--extra-index-url https://pypi.org/simple\n"
        "http://example.com/package.tar.gz\n"
        "https://example.com/package-1.0.0.whl\n"
        "git+https://github.com/org/repo.git@v1.0\n"
        "pkg @ https://github.com/org/repo/archive/v1.0.zip\n"
        "pkg @ file:///local/path\n"
        "./local-wheel-0.1.0-py3-none-any.whl\n"
        "valid-package==1.0.0\n"
    )
    with mock.patch("codeprism.security.cve.check_package", side_effect=record_call):
        cve.check_requirements(reqs)

        assert calls == [("valid-package", "1.0.0")]
