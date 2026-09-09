from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.core.config import settings

Base = declarative_base()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def init_db():
    """Initializes schema tables and applies idempotent migrations (B07)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def migrate(sync_conn):
            from sqlalchemy import inspect, text
            inspector = inspect(sync_conn)
            
            # 1. Check tenants.version (OCC lock)
            if "tenants" in inspector.get_table_names():
                columns = [col["name"] for col in inspector.get_columns("tenants")]
                if "version" not in columns:
                    sync_conn.execute(text("ALTER TABLE tenants ADD COLUMN version INTEGER DEFAULT 0 NOT NULL"))
            
            # 2. Check entitlements.payment_intent
            if "entitlements" in inspector.get_table_names():
                columns = [col["name"] for col in inspector.get_columns("entitlements")]
                if "payment_intent" not in columns:
                    sync_conn.execute(text("ALTER TABLE entitlements ADD COLUMN payment_intent VARCHAR(255)"))
                    
            # 3. Check usage_reservations.request_hash
            if "usage_reservations" in inspector.get_table_names():
                columns = [col["name"] for col in inspector.get_columns("usage_reservations")]
                if "request_hash" not in columns:
                    sync_conn.execute(text("ALTER TABLE usage_reservations ADD COLUMN request_hash VARCHAR(64)"))

        await conn.run_sync(migrate)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency yielding transactional database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
