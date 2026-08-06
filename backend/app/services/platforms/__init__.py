"""Platform artifact bundler registry and factory.

Usage:
    from app.services.platforms import get_bundler, BundleConfig

    bundler = get_bundler("agentcore")
    result = bundler.build_artifact(config)
"""

from app.services.platforms.base import ArtifactBundler, ArtifactResult, BundleConfig
from app.services.platforms.agentcore import AgentCoreBundler

__all__ = [
    "ArtifactBundler",
    "ArtifactResult",
    "BundleConfig",
    "AgentCoreBundler",
    "get_bundler",
    "register_bundler",
]

# Provider registry — maps provider slug to bundler class.
_REGISTRY: dict[str, type[ArtifactBundler]] = {
    "agentcore": AgentCoreBundler,
}


def get_bundler(provider: str) -> ArtifactBundler:
    """Resolve and instantiate a bundler by provider slug.

    Args:
        provider: Provider identifier (e.g. 'agentcore').

    Returns:
        An instance of the corresponding ArtifactBundler implementation.

    Raises:
        KeyError: If the provider is not registered.
    """
    cls = _REGISTRY.get(provider)
    if cls is None:
        raise KeyError(
            f"Unknown deployment platform: {provider!r}. "
            f"Available: {list(_REGISTRY.keys())}"
        )
    return cls()


def register_bundler(name: str, cls: type[ArtifactBundler]) -> None:
    """Register an additional bundler provider.

    This allows external plugins or future implementations to add
    new platform support without modifying this package.

    Args:
        name: Provider slug (must be unique).
        cls: ArtifactBundler subclass to register.
    """
    _REGISTRY[name] = cls
