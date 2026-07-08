"""HandoffRail API Server — Schema Registry endpoints.

POST   /schemas            — Register a new JSON schema
GET    /schemas            — List all schemas for the tenant
GET    /schemas/{id}       — Get schema details by ID
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_api_key_from_request
from app.models.db import ApiKey, Schema
from app.models.packet import SchemaCreate, SchemaListResponse, SchemaResponse

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/schemas", tags=["schemas"])


def _schema_to_response(schema: Schema) -> SchemaResponse:
    """Convert an ORM Schema to a Pydantic response model."""
    return SchemaResponse(
        id=schema.id,
        name=schema.name,
        version=schema.version,
        json_schema=schema.get_json_schema(),
        tenant_id=schema.tenant_id,
        created_at=schema.created_at,
    )


@router.post(
    "",
    response_model=SchemaResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_schema(
    payload: SchemaCreate,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> SchemaResponse:
    """Register a new JSON schema for packet context validation.

    The schema is stored and associated with the authenticated tenant.
    Schemas with the same name will create a new entry (versioning is
    managed by the caller via the version field).
    """
    schema_id = str(uuid4())
    now = datetime.now(UTC)

    db_schema = Schema(
        id=schema_id,
        name=payload.name,
        version=payload.version,
        json_schema=__import__("json").dumps(payload.json_schema, default=str),
        tenant_id=api_key.tenant_id,
        created_at=now,
    )

    db.add(db_schema)
    await db.commit()
    await db.refresh(db_schema)

    logger.info(
        "schema_created",
        schema_id=schema_id,
        name=payload.name,
        version=payload.version,
        tenant_id=api_key.tenant_id,
    )

    return _schema_to_response(db_schema)


@router.get(
    "",
    response_model=SchemaListResponse,
)
async def list_schemas(
    limit: int = Query(50, ge=1, le=200, description="Max results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> SchemaListResponse:
    """List all schemas for the authenticated tenant."""
    count_query = select(func.count()).where(Schema.tenant_id == api_key.tenant_id)
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    query = (
        select(Schema)
        .where(Schema.tenant_id == api_key.tenant_id)
        .order_by(Schema.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    schemas = result.scalars().all()

    return SchemaListResponse(
        schemas=[_schema_to_response(s) for s in schemas],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{schema_id}",
    response_model=SchemaResponse,
    responses={
        404: {"description": "Schema not found"},
    },
)
async def get_schema(
    schema_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key_from_request),
) -> SchemaResponse:
    """Get a single schema by ID. Scoped to the authenticated tenant."""
    result = await db.execute(
        select(Schema).where(Schema.id == schema_id, Schema.tenant_id == api_key.tenant_id)
    )
    schema = result.scalar_one_or_none()

    if schema is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schema {schema_id} not found",
        )

    return _schema_to_response(schema)
