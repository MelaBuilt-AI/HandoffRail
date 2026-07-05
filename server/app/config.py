"""HandoffRail API Server — Environment-based configuration using pydantic-settings."""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Supports dev / staging / prod environments with sensible defaults for dev.
    """

    # ── Environment ──────────────────────────────────────────────────────────
    environment: Literal["dev", "staging", "prod"] = "dev"

    # ── Database ─────────────────────────────────────────────────────────────
    # SQLite for dev, PostgreSQL for staging/prod
    database_url: str = "sqlite+aiosqlite:///./handoffrail.db"

    # ── Redis ────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Tier defaults ────────────────────────────────────────────────────────
    tier_default: str = "free"

    # ── Logging ──────────────────────────────────────────────────────────────
    log_level: str = "info"

    # ── Server ───────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8080

    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: list[str] = ["*"]

    # ── Tier quota limits ───────────────────────────────────────────────────
    # Handoffs per day, max agents, max API keys, max packet size (bytes)
    tier_quotas: dict[str, dict[str, int | bool]] = {
        "free": {
            "handoffs_per_day": 5,
            "max_agents": 2,
            "max_api_keys": 1,
            "max_packet_size": 64 * 1024,  # 64KB
            "unlimited_handoffs": False,
        },
        "pro": {
            "handoffs_per_day": 0,  # unlimited
            "max_agents": 10,
            "max_api_keys": 5,
            "max_packet_size": 256 * 1024,  # 256KB
            "unlimited_handoffs": True,
        },
        "business": {
            "handoffs_per_day": 0,  # unlimited
            "max_agents": 50,
            "max_api_keys": 25,
            "max_packet_size": 1024 * 1024,  # 1MB
            "unlimited_handoffs": True,
        },
    }

    # ── Rate limit tiers (requests per hour) ─────────────────────────────────
    rate_limit_tiers: dict[str, int] = {
        "free": 100,
        "pro": 1000,
        "business": 10000,
    }

    # ── WebSocket connection limits per tier ──────────────────────────────────
    ws_connection_limits: dict[str, int] = {
        "free": 1,
        "pro": 5,
        "business": 25,
    }

    # ── Batch operations ────────────────────────────────────────────────────
    batch_max_size: int = 50

    model_config = {
        "env_prefix": "HR_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    def is_postgres(self) -> bool:
        """Check if the DATABASE_URL points to PostgreSQL."""
        return self.database_url.startswith("postgresql")

    def is_dev(self) -> bool:
        """Check if running in dev mode."""
        return self.environment == "dev"

    def get_cors_origins(self) -> list[str]:
        """Get CORS origins — restrict in prod."""
        if self.environment == "prod" and self.cors_origins == ["*"]:
            # In prod, warn about wildcard CORS
            import structlog

            structlog.get_logger().warning(
                "cors_wildcard_in_prod",
                message="CORS allows all origins in production — set HR_CORS_ORIGINS explicitly",
            )
        return self.cors_origins


# Module-level settings instance — lazy loaded
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get the application settings (cached singleton)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset settings — useful for tests."""
    global _settings
    _settings = None
