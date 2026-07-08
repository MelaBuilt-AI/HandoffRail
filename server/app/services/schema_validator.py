"""Schema validation service — validates packet context against registered JSON schemas."""

from __future__ import annotations

from typing import Any

import jsonschema
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import Schema

logger = structlog.get_logger()


async def validate_context_against_schema(
    schema_id: str,
    context: dict[str, Any],
    db: AsyncSession,
    tenant_id: str,
) -> str | None:
    """Validate a context dict against a registered JSON schema.

    Args:
        schema_id: The schema UUID to validate against.
        context: The packet context dict to validate.
        db: Database session for schema lookup.
        tenant_id: Tenant ID for scoping the schema lookup.

    Returns:
        None if validation passes, or an error message string if validation fails.
    """
    # Look up the schema
    result = await db.execute(
        select(Schema).where(Schema.id == schema_id, Schema.tenant_id == tenant_id)
    )
    schema_record = result.scalar_one_or_none()

    if schema_record is None:
        return f"Schema '{schema_id}' not found for this tenant"

    # Parse the stored JSON schema
    try:
        schema_dict = schema_record.get_json_schema()
    except (ValueError, TypeError) as exc:
        logger.warning("schema_parse_error", schema_id=schema_id, error=str(exc))
        return f"Schema '{schema_id}' has an invalid JSON schema definition"

    # Validate context against the schema
    try:
        jsonschema.validate(instance=context, schema=schema_dict)
        logger.info(
            "schema_validation_passed",
            schema_id=schema_id,
            schema_name=schema_record.name,
        )
        return None
    except jsonschema.exceptions.ValidationError as exc:
        # Build a descriptive error message from the validation error
        path = ".".join(str(p) for p in exc.absolute_path) if exc.absolute_path else "root"
        error_msg = f"Context validation failed: {exc.message} (at '{path}')"
        logger.warning(
            "schema_validation_failed",
            schema_id=schema_id,
            error=error_msg,
        )
        return error_msg
