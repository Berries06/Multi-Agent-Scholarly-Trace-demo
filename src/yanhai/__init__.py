"""Core package for the Yanhai scholarly trace demonstrator."""

from .orchestrator import ScholarlyTraceOrchestrator
from .config import FeatureFlags, SystemConfig, get_preset, list_presets
from .providers import ProviderConfig, list_providers

__all__ = [
    "FeatureFlags",
    "ScholarlyTraceOrchestrator",
    "SystemConfig",
    "ProviderConfig",
    "get_preset",
    "list_providers",
    "list_presets",
]
__version__ = "0.1.0"
