"""Tests for CodePrism configuration loading and validation."""

import tomllib
from pathlib import Path

import pytest

from codeprism.core.config import CodePrismConfig


def test_valid_configuration(tmp_path: Path):
    """A valid .codeprism.toml continues to load successfully."""
    config_file = tmp_path / ".codeprism.toml"
    config_file.write_text(
        "[codeprism]\n"
        "watch_debounce_ms = 150\n"
        'languages = ["python", "go"]\n'
        "\n"
        "[codeprism.security]\n"
        "block_on_secrets = false\n"
        'ignore_paths = ["vendor/*"]\n'
    )

    cfg = CodePrismConfig.load(config_file)
    assert cfg.watch_debounce_ms == 150
    assert cfg.languages == ["python", "go"]
    assert cfg.security.block_on_secrets is False
    assert cfg.security.ignore_paths == ["vendor/*"]


def test_unknown_key_rejected(tmp_path: Path):
    """An unknown key at the root is rejected and identified."""
    config_file = tmp_path / ".codeprism.toml"
    # Typo: langauges instead of languages
    config_file.write_text('[codeprism]\nlangauges = ["python"]\n')

    with pytest.raises(ValueError, match="Unknown configuration key: 'langauges'"):
        CodePrismConfig.load(config_file)


def test_misplaced_key_rejected(tmp_path: Path):
    """A valid option in the wrong section is rejected and identified."""
    config_file = tmp_path / ".codeprism.toml"
    # ignore_paths belongs under [codeprism.security], not root
    config_file.write_text('[codeprism]\nignore_paths = ["vendor/*"]\n')

    with pytest.raises(ValueError, match="Unknown configuration key: 'ignore_paths'"):
        CodePrismConfig.load(config_file)


def test_invalid_type_rejected(tmp_path: Path):
    """An existing field with an invalid type throws a useful error."""
    config_file = tmp_path / ".codeprism.toml"
    # watch_debounce_ms must be an int
    config_file.write_text('[codeprism]\nwatch_debounce_ms = "a string"\n')

    with pytest.raises(ValueError, match="Configuration error at 'watch_debounce_ms'"):
        CodePrismConfig.load(config_file)


def test_invalid_toml_syntax(tmp_path: Path):
    """Invalid TOML syntax preserves the TOML decode error."""
    config_file = tmp_path / ".codeprism.toml"
    config_file.write_text("[codeprism\nwatch_debounce_ms = 100\n")

    with pytest.raises(tomllib.TOMLDecodeError):
        CodePrismConfig.load(config_file)


def test_mcp_startup_logs_error(tmp_path: Path, monkeypatch, capsys):
    """MCP _lifespan should log configuration errors to stderr and continue."""
    import asyncio

    from fastmcp import FastMCP

    import codeprism.mcp.server
    from codeprism.mcp.server import _lifespan

    config_file = tmp_path / ".codeprism.toml"
    config_file.write_text("[codeprism]\ninvalid_key = 1\n")

    monkeypatch.setattr(codeprism.mcp.server, "_project_path", str(tmp_path))

    mcp = FastMCP("test")

    async def run_lifespan():
        async with _lifespan(mcp):
            pass

    asyncio.run(run_lifespan())

    captured = capsys.readouterr()
    assert "CodePrism configuration error: Unknown configuration key: 'invalid_key'" in captured.err
