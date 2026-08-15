"""CodePrismConfig — loaded from .codeprism.toml or the user config dir."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class SecurityConfig(BaseModel):
    block_on_secrets: bool = True
    warn_on_weak_crypto: bool = True
    check_new_dependencies: bool = True
    ignore_paths: list[str] = Field(default_factory=list)


class EmbeddingsConfig(BaseModel):
    model: str = "all-MiniLM-L6-v2"
    device: str = "cpu"


class MCPConfig(BaseModel):
    transport: str = "stdio"
    port: int = 8765


class CodePrismConfig(BaseModel):
    project_path: Optional[str] = None
    languages: list[str] = Field(
        default_factory=lambda: ["python", "javascript", "typescript"]
    )
    enable_embeddings: bool = False
    enable_security_gate: bool = True
    watch_debounce_ms: int = 500
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)

    @classmethod
    def load(cls, path: Path) -> "CodePrismConfig":
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
        return cls(**raw, **nested)

    @classmethod
    def default(cls) -> "CodePrismConfig":
        return cls()
