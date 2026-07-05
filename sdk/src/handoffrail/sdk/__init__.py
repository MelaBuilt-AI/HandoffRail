"""HandoffRail Python SDK — session-continuity middleware for multi-agent AI workflows."""

from handoffrail.sdk.client import HandoffRailClient
from handoffrail.sdk.async_client import AsyncHandoffRailClient
from handoffrail.sdk.models import (
    PacketCreate,
    PacketResponse,
    PacketListResponse,
    PacketClaim,
    PacketUpdate,
    WebhookCreate,
    WebhookResponse,
    PacketEvent,
    ChainHandoffRequest,
    BatchCreateResponse,
    BatchClaimRequest,
    BatchClaimResponse,
    BatchCompleteRequest,
    BatchCompleteResponse,
    SearchOptions,
)
from handoffrail.sdk.builders import PacketBuilder, ChainBuilder
from handoffrail.sdk.exceptions import (
    HandoffRailError,
    AuthenticationError,
    NotFoundError,
    ValidationError,
    RateLimitError,
    ServerError,
    ConnectionError,
)

# WebSocket client — lazy import, requires websockets package
# from handoffrail.sdk.ws_client import HandoffRailWSClient

__all__ = [
    # Client
    "HandoffRailClient",
    "AsyncHandoffRailClient",
    # Models
    "PacketCreate",
    "PacketResponse",
    "PacketListResponse",
    "PacketClaim",
    "PacketUpdate",
    "WebhookCreate",
    "WebhookResponse",
    "PacketEvent",
    "ChainHandoffRequest",
    "BatchCreateResponse",
    "BatchClaimRequest",
    "BatchClaimResponse",
    "BatchCompleteRequest",
    "BatchCompleteResponse",
    "SearchOptions",
    # Builders
    "PacketBuilder",
    "ChainBuilder",
    # Exceptions
    "HandoffRailError",
    "AuthenticationError",
    "NotFoundError",
    "ValidationError",
    "RateLimitError",
    "ServerError",
    "ConnectionError",
    # WebSocket
    "HandoffRailWSClient",
]

__version__ = "0.1.0"


def __getattr__(name: str):
    """Lazy-load integration classes so langchain/crewai are not required
    unless the user explicitly imports them."""
    integrations = {
        "BaseAdapter": "handoffrail.integrations.base",
        "LangChainAdapter": "handoffrail.integrations.langchain",
        "HandoffRailCallbackHandler": "handoffrail.integrations.langchain",
        "HandoffRailTool": "handoffrail.integrations.langchain",
        "CrewAIAdapter": "handoffrail.integrations.crewai",
        "HandoffRailCrewAITool": "handoffrail.integrations.crewai",
        "HandoffRailWSClient": "handoffrail.sdk.ws_client",
    }
    if name in integrations:
        import importlib
        module = importlib.import_module(integrations[name])
        return getattr(module, name)
    raise AttributeError(f"module 'handoffrail.sdk' has no attribute {name!r}")
