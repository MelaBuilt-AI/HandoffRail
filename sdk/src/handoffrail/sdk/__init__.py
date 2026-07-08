"""HandoffRail Python SDK — session-continuity middleware for multi-agent AI workflows."""

from handoffrail.sdk.async_client import AsyncHandoffRailClient
from handoffrail.sdk.builders import ChainBuilder, PacketBuilder
from handoffrail.sdk.client import HandoffRailClient
from handoffrail.sdk.exceptions import (
    AuthenticationError,
    ConnectionError,
    HandoffRailError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from handoffrail.sdk.models import (
    ApiKeyCreate,
    ApiKeyResponse,
    AuditLogResponse,
    BatchClaimRequest,
    BatchClaimResponse,
    BatchCompleteRequest,
    BatchCompleteResponse,
    BatchCreateResponse,
    ChainHandoffRequest,
    PacketClaim,
    PacketCreate,
    PacketEvent,
    PacketListResponse,
    PacketResponse,
    PacketUpdate,
    SchemaCreate,
    SchemaListResponse,
    SchemaResponse,
    SearchOptions,
    WebhookCreate,
    WebhookResponse,
)

# WebSocket client — lazy import, requires websockets package
# from handoffrail.sdk.ws_client import HandoffRailWSClient

# SSE client — lazy import, requires httpx package
# from handoffrail.sdk.sse_client import HandoffRailSSEClient

__all__ = [
    # Client
    "HandoffRailClient",
    "AsyncHandoffRailClient",
    # Models
    "ApiKeyCreate",
    "ApiKeyResponse",
    "PacketCreate",
    "PacketResponse",
    "PacketListResponse",
    "AuditLogResponse",
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
    # SSE
    "HandoffRailSSEClient",
]

__version__ = "0.2.0"


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
        "HandoffRailSSEClient": "handoffrail.sdk.sse_client",

    }
    if name in integrations:
        import importlib
        module = importlib.import_module(integrations[name])
        return getattr(module, name)
    raise AttributeError(f"module 'handoffrail.sdk' has no attribute {name!r}")
