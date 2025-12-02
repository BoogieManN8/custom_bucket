import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import BigInteger, Boolean, Float, Integer, JSON, SmallInteger, String, func
from sqlalchemy.dialects.mysql import TIMESTAMP as MYSQL_TIMESTAMP, VARBINARY
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

logger = logging.getLogger(__name__)


def _build_database_url() -> str:
    """Assemble the SQLAlchemy DSN using asyncmy driver (fast, pure-Python, fully supported)."""
    default_url = "mysql+asyncmy://asset_user:asset_pass@db:3306/assets_bucket"
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url

    user = os.getenv("DB_USER", "asset_user")
    password = os.getenv("DB_PASSWORD", "asset_pass")
    host = os.getenv("DB_HOST", "db")
    port = os.getenv("DB_PORT", "3306")
    name = os.getenv("DB_NAME", "assets_bucket")
    return f"mysql+asyncmy://{user}:{password}@{host}:{port}/{name}"


DATABASE_URL = _build_database_url()


class Base(DeclarativeBase):
    pass


engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    future=True,
    echo=False,  # set to True only for debugging
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class MediaAsset(Base):
    __tablename__ = "media_assets"

    uid: Mapped[bytes] = mapped_column(VARBINARY(16), primary_key=True)
    aspect_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    collection_name: Mapped[str | None] = mapped_column(String(255))
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_type: Mapped[str | None] = mapped_column(String(255))
    folder: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(255))
    extension: Mapped[str | None] = mapped_column(String(255))
    disk: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    manipulations: Mapped[Dict[str, Any] | None] = mapped_column(JSON)
    custom_properties: Mapped[Dict[str, Any] | None] = mapped_column(JSON)
    responsive_images: Mapped[Dict[str, Any] | None] = mapped_column(JSON)
    order_column: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
    deleted_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime | None] = mapped_column(
        MYSQL_TIMESTAMP(fsp=6), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        MYSQL_TIMESTAMP(fsp=6), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(MYSQL_TIMESTAMP(fsp=6))
    is_paragraph: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)


async def init_db(retries: int = 10, delay_seconds: float = 3.0) -> None:
    """Create tables with retry logic while MySQL starts up."""
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables created successfully.")
            return
        except OperationalError as exc:
            last_error = exc
            logger.warning(
                "Failed to connect to database (attempt %s/%s). Retrying in %.1fs...",
                attempt, retries, delay_seconds
            )
            await asyncio.sleep(delay_seconds)
    if last_error:
        logger.error("Failed to initialize database after %s attempts.", retries)
        raise last_error


async def get_session():
    """Dependency generator for FastAPI."""
    async with AsyncSessionLocal() as session:
        yield session
