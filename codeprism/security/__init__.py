"""Security scanning package."""

from .cve import CVEResult, check_package, check_requirements
from .detectors import (
    BaseDetector,
    DependenciesDetector,
    DetectionResult,
    EnvVarDetector,
    GitSafetyDetector,
    InjectionDetector,
    SecretsDetector,
    WeakCryptoDetector,
)
from .gate import SecurityGate
from .scanner import SecurityReport, SecurityScanner

__all__ = [
    "SecurityGate",
    "SecurityScanner",
    "SecurityReport",
    "DetectionResult",
    "BaseDetector",
    "SecretsDetector",
    "InjectionDetector",
    "WeakCryptoDetector",
    "EnvVarDetector",
    "DependenciesDetector",
    "GitSafetyDetector",
    "CVEResult",
    "check_package",
    "check_requirements",
]
