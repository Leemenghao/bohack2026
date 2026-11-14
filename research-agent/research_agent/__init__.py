"""Deep Agents package."""

from research_agent._version import __version__
from research_agent.graph import (
    DeepAgentState,
    create_deep_agent,
)
from research_agent.middleware.async_subagents import AsyncSubAgent, AsyncSubAgentMiddleware
from research_agent.middleware.filesystem import FilesystemMiddleware, FilesystemPermission, FsToolName
from research_agent.middleware.memory import MemoryMiddleware
from research_agent.middleware.rubric import RubricMiddleware
from research_agent.middleware.subagents import (
    CompiledSubAgent,
    SubAgent,
    SubAgentMiddleware,
)
from research_agent.profiles.harness.harness_profiles import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    HarnessProfileConfig,
    register_harness_profile,
)
from research_agent.profiles.provider.provider_profiles import (
    ProviderProfile,
    register_provider_profile,
)

__all__ = [
    "AsyncSubAgent",
    "AsyncSubAgentMiddleware",
    "CompiledSubAgent",
    "DeepAgentState",
    "FilesystemMiddleware",
    "FilesystemPermission",
    "FsToolName",
    "GeneralPurposeSubagentProfile",
    "HarnessProfile",
    "HarnessProfileConfig",
    "MemoryMiddleware",
    "ProviderProfile",
    "RubricMiddleware",
    "SubAgent",
    "SubAgentMiddleware",
    "__version__",
    "create_deep_agent",
    "register_harness_profile",
    "register_provider_profile",
]
