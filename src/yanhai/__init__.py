"""Core package for the Yanhai scholarly trace demonstrator."""

from .orchestrator import ScholarlyTraceOrchestrator
from .providers import ProviderConfig, list_providers

__all__ = [
    "ScholarlyTraceOrchestrator",
    "ProviderConfig",
    "list_providers",
]
__version__ = "0.1.0"
