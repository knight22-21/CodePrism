from unittest import mock

from codeprism.security import cve


def mock_check_package(pkg: str) -> cve.CVEResult:
    # A mock that just returns the package name so we can record it
    # We set severity to "HIGH" so it gets included in the results list,
    # otherwise check_requirements filters out "PASS" and "UNKNOWN".
    return cve.CVEResult(package=pkg, version="", cve_ids=[], severity="HIGH", summary="")


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


def test_check_requirements_skips_valid_packages():
    # If check_package returns PASS or UNKNOWN, it should be filtered out
    def mock_pass(pkg: str):
        return cve.CVEResult(package=pkg, version="", severity="PASS")

    with mock.patch("codeprism.security.cve.check_package", side_effect=mock_pass):
        results = cve.check_requirements("flask")
        assert len(results) == 0
