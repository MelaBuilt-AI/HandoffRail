"""HandoffRail integrations — framework adapters for LangChain, CrewAI, and custom agents.

Each adapter lives in its own submodule and the framework dependency is optional.
Import the specific submodule only when you need it — importing this package does
not require langchain or crewai to be installed.
"""

from __future__ import annotations

__all__ = [
    "BaseAdapter",
    "LangChainAdapter",
    "HandoffRailCallbackHandler",
    "HandoffRailTool",
    "CrewAIAdapter",
    "HandoffRailCrewAITool",
]


def __getattr__(name: str):
    """Lazy-load integration classes so langchain/crewai are only imported when needed."""
    if name == "BaseAdapter":
        from handoffrail.integrations.base import BaseAdapter
        return BaseAdapter
    if name == "LangChainAdapter":
        from handoffrail.integrations.langchain import LangChainAdapter
        return LangChainAdapter
    if name == "HandoffRailCallbackHandler":
        from handoffrail.integrations.langchain import HandoffRailCallbackHandler
        return HandoffRailCallbackHandler
    if name == "HandoffRailTool":
        from handoffrail.integrations.langchain import HandoffRailTool
        return HandoffRailTool
    if name == "CrewAIAdapter":
        from handoffrail.integrations.crewai import CrewAIAdapter
        return CrewAIAdapter
    if name == "HandoffRailCrewAITool":
        from handoffrail.integrations.crewai import HandoffRailCrewAITool
        return HandoffRailCrewAITool
    raise AttributeError(f"module 'handoffrail.integrations' has no attribute {name!r}")
