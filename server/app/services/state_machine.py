"""HandoffRail API Server — Packet status state machine.

Defines the valid state transitions for packet lifecycle:
  created → claimed → in_progress → completed
  created → awaiting_human → claimed → in_progress → completed
  Any state → failed (except completed, expired)
  Any state → expired (via soft delete or TTL)
"""

from __future__ import annotations

from enum import StrEnum

from fastapi import HTTPException, status


class StatusTransition(StrEnum):
    """Named status transitions for audit logging."""

    CREATE = "created"
    CLAIM = "claimed"
    START = "in_progress"
    AWAIT_HUMAN = "awaiting_human"
    RESPOND = "responded"
    COMPLETE = "completed"
    FAIL = "failed"
    EXPIRE = "expired"


# Valid transitions: {from_status: {to_status: transition_name}}
VALID_TRANSITIONS: dict[str, dict[str, str]] = {
    "created": {
        "claimed": StatusTransition.CLAIM.value,
        "awaiting_human": StatusTransition.AWAIT_HUMAN.value,
        "failed": StatusTransition.FAIL.value,
        "expired": StatusTransition.EXPIRE.value,
    },
    "claimed": {
        "in_progress": StatusTransition.START.value,
        "awaiting_human": StatusTransition.AWAIT_HUMAN.value,
        "failed": StatusTransition.FAIL.value,
        "expired": StatusTransition.EXPIRE.value,
    },
    "in_progress": {
        "completed": StatusTransition.COMPLETE.value,
        "awaiting_human": StatusTransition.AWAIT_HUMAN.value,
        "failed": StatusTransition.FAIL.value,
        "expired": StatusTransition.EXPIRE.value,
    },
    "awaiting_human": {
        "claimed": StatusTransition.CLAIM.value,
        "in_progress": StatusTransition.START.value,
        "failed": StatusTransition.FAIL.value,
        "expired": StatusTransition.EXPIRE.value,
    },
    "completed": {
        "expired": StatusTransition.EXPIRE.value,
    },
    "failed": {
        "expired": StatusTransition.EXPIRE.value,
    },
    "expired": {},  # Terminal state — no transitions out
}

# Terminal states: packets in these states cannot transition further
TERMINAL_STATES = {"completed", "expired"}


class InvalidTransitionError(HTTPException):
    """Raised when a status transition is not allowed."""

    def __init__(self, current_status: str, target_status: str) -> None:
        allowed = list(VALID_TRANSITIONS.get(current_status, {}).keys())
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot transition from '{current_status}' to '{target_status}'. "
                f"Allowed transitions from '{current_status}': {allowed}"
            ),
        )


def validate_transition(current_status: str, target_status: str) -> str:
    """Validate that a status transition is allowed.

    Args:
        current_status: The packet's current status.
        target_status: The desired new status.

    Returns:
        The transition name if valid.

    Raises:
        InvalidTransitionError: If the transition is not allowed.
    """
    transitions = VALID_TRANSITIONS.get(current_status, {})
    transition_name = transitions.get(target_status)

    if transition_name is None:
        raise InvalidTransitionError(current_status, target_status)

    return transition_name


def can_transition(current_status: str, target_status: str) -> bool:
    """Check if a status transition is allowed without raising."""
    return target_status in VALID_TRANSITIONS.get(current_status, {})


def get_allowed_transitions(current_status: str) -> list[str]:
    """Return the list of statuses a packet can transition to from its current status."""
    return list(VALID_TRANSITIONS.get(current_status, {}).keys())


def is_terminal(status: str) -> bool:
    """Check if a status is terminal (no further transitions allowed)."""
    return status in TERMINAL_STATES
