"""研海寻踪（Yanhai）科研溯源演示项目的核心包。"""

from .orchestrator import ScholarlyTraceOrchestrator
from .providers import ProviderConfig, list_providers

__all__ = [
    "ScholarlyTraceOrchestrator",
    "ProviderConfig",
    "list_providers",
]
__version__ = "0.1.0"
