"""Abstract base class and data structures for platform artifact bundlers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BundleConfig:
    """Provider-agnostic bundling parameters.

    Attributes:
        region: Cloud region for artifact storage (e.g. 'us-east-1').
        source_dir: Path to agent source code directory.
        requirements: Path to requirements.txt (or equivalent manifest).
        python_version: Target Python version for dependency resolution.
        target_platform: pip --platform value for cross-compilation.
        extra: Provider-specific overrides (varies by implementation).
    """

    region: str
    source_dir: Path
    requirements: Path
    python_version: str = "3.13"
    target_platform: str = "manylinux2014_aarch64"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ArtifactResult:
    """Output of a successful build_artifact() call.

    Attributes:
        provider: Slug identifying the provider (e.g. 'agentcore').
        location: Provider-specific locator for the published artifact.
            - agentcore: {"bucket": "...", "key": "..."}
        metadata: Optional extra info (size, sha256, timestamps, etc.).
    """

    provider: str
    location: dict[str, str]
    metadata: dict[str, Any] = field(default_factory=dict)


class ArtifactBundler(ABC):
    """Contract that every deployment-platform bundler must satisfy.

    Implementations package agent source code into a deployable artifact
    and publish it to the appropriate storage backend.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique slug identifying this provider (e.g. 'agentcore')."""
        ...

    @abstractmethod
    def build_artifact(self, config: BundleConfig) -> ArtifactResult:
        """Build and publish the deployment artifact.

        Args:
            config: Bundling parameters (source, requirements, region, etc.).

        Returns:
            ArtifactResult with provider-specific location info.

        Raises:
            ValueError: Missing required configuration.
            FileNotFoundError: Source code or requirements missing.
            RuntimeError: Build or publish step failed.
        """
        ...
