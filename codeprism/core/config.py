"""CodePrismConfig — loaded from .codeprism.toml or the user config dir."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .languages import SUPPORTED_LANGUAGES


class SecurityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_on_secrets: bool = True
    warn_on_weak_crypto: bool = True
    check_new_dependencies: bool = True
    ignore_paths: list[str] = Field(default_factory=list)


class EmbeddingsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = "all-MiniLM-L6-v2"
    device: str = "cpu"


class MCPConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transport: str = "stdio"
    port: int = 8765


class CodePrismConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_path: str | None = None
    languages: list[str] = Field(default_factory=lambda: list(SUPPORTED_LANGUAGES))
    enable_embeddings: bool = False
    enable_security_gate: bool = True
    watch_debounce_ms: int = 500
    # Skip files git ignores (vendored checkouts, build output, generated code)
    respect_gitignore: bool = True
    # `codeprism serve` builds / refreshes the index in the background at startup
    auto_index: bool = True
    # Processes used to parse large indexes: 1 = in-process (library default),
    # 0 = one per CPU core, N = N processes. The CLI and MCP server use 0.
    # Worker processes re-import the caller's __main__ on Windows/macOS, so
    # scripts that opt in need an `if __name__ == "__main__":` guard.
    parse_workers: int = 1
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)

    @classmethod
    def load(cls, path: Path) -> CodePrismConfig:
        """Load config from a TOML file; returns defaults if file absent."""
        if not path.exists():
            return cls()
        with open(path, "rb") as f:
            data = tomllib.load(f)
        raw = data.get("codeprism", {})
        # Nested sections need special handling
        nested = {}
        for key in ("security", "embeddings", "mcp"):
            if key in raw:
                nested[key] = raw.pop(key)
        try:
            return cls(**raw, **nested)
        except ValidationError as e:
            msg = []
            for err in e.errors():
                loc = ".".join(str(x) for x in err["loc"])
                if err["type"] == "extra_forbidden":
                    msg.append(f"Unknown configuration key: '{loc}'")
                else:
                    msg.append(f"Configuration error at '{loc}': {err.get('msg', 'invalid value')}")
            raise ValueError(", ".join(msg)) from e

    @classmethod
    def default(cls) -> CodePrismConfig:
        return cls()
