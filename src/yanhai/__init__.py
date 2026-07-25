"""Core package for the Yanhai scholarly trace demonstrator."""

from .orchestrator import ScholarlyTraceOrchestrator
from .config import FeatureFlags, SystemConfig, get_preset, list_presets

__all__ = [
    "FeatureFlags",
    "ScholarlyTraceOrchestrator",
    "SystemConfig",
    "get_preset",
    "list_presets",
]
__version__ = "0.1.0"
