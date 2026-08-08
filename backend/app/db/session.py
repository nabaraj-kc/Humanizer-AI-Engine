"""
backend/app/db/session.py
=========================
Asynchronous database session layer targeting a local SQLite instance.

GUARDRAIL RECOVERY NOTE:
  SQLAlchemy 2.x's async bridge (create_async_engine + aiosqlite) triggers
  a Windows access violation (0xC0000005) on Python 3.11.0a2 due to
  greenlet/asyncio incompatibilities in the alpha build. The recovery path
  per Stage 3's guardrail specification routes to a direct aiosqlite
  connection factory. All downstream ORM models (Stage 4) continue to use
  SQLAlchemy's declarative metadata for schema definition and table creation,
  while raw query execution is performed through the aiosqlite layer.

Key design decisions:
  - Absolute path construction via pathlib to prevent relative-path drift.
  - PRAGMA foreign_keys = ON enforced on every new connection.
  - Context manager pattern guarantees session cleanup even under exceptions.
  - expire_on_commit semantics are handled via explicit refresh patterns.
"""

import asyncio
import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

# ---------------------------------------------------------------------------
# Path Resolution
# ---------------------------------------------------------------------------
_THIS_FILE = Path(__file__).resolve()                # absolute path to session.py
_THIS_DIR = _THIS_FILE.parent                        # .../backend/app/db/
_PROJECT_ROOT = _THIS_DIR.parents[2]                 # db(0)->app(1)->backend(2) => humanizer ai/
_STORAGE_DIR = _PROJECT_ROOT / "storage"
_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = _STORAGE_DIR / "humanizer.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DATABASE_PATH.as_posix()}"

# ---------------------------------------------------------------------------
# SQLAlchemy engine (for ORM metadata / schema generation only)
# ---------------------------------------------------------------------------
# We use SQLAlchemy's synchronous engine exclusively for CREATE TABLE
# operations and schema introspection. All runtime queries go through
# the aiosqlite async session below.
from sqlalchemy import create_engine, event as sa_event

_sync_engine = create_engine(
    f"sqlite:///{DATABASE_PATH}",
    connect_args={"check_same_thread": False},
)


@sa_event.listens_for(_sync_engine, "connect")
def _set_sqlite_pragma_sync(dbapi_connection, connection_record):
    """Enable FK constraints on sync engine connections (used for schema ops)."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.close()


def get_sync_engine():
    """Return the synchronous SQLAlchemy engine (schema management only)."""
    return _sync_engine


# ---------------------------------------------------------------------------
# Async Session via aiosqlite
# ---------------------------------------------------------------------------

@asynccontextmanager
async def get_async_session() -> AsyncGenerator[aiosqlite.Connection, None]:
    """
    Yield an active aiosqlite Connection as the async session.
    Enforces:
      - PRAGMA foreign_keys = ON on every connection
      - Automatic ROLLBACK on exception
      - Guaranteed connection close in finally block

    Usage:
        async with get_async_session() as db:
            await db.execute("SELECT 1")
    """
    db: aiosqlite.Connection = await aiosqlite.connect(str(DATABASE_PATH))
    db.row_factory = aiosqlite.Row
    try:
        await db.execute("PRAGMA foreign_keys = ON;")
        yield db
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


# Alias matching the FastAPI dependency injection signature
async def get_async_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """FastAPI dependency alias for get_async_session."""
    async with get_async_session() as db:
        yield db


# ---------------------------------------------------------------------------
# Integration Test
# ---------------------------------------------------------------------------
async def _run_integration_test() -> None:
    print("=== Stage 3: Database Integration Test ===")
    print(f"  Engine URL : {DATABASE_URL}")
    print(f"  DB Path    : {DATABASE_PATH}")
    print()

    try:
        async with get_async_session() as db:
            # Test 1: Basic connectivity
            async with db.execute("SELECT 1") as cursor:
                row = await cursor.fetchone()
                assert row[0] == 1, f"Expected 1, got {row[0]}"
            print(f"  [PASS] SELECT 1 = {row[0]}")

            # Test 2: FK pragma enforcement
            async with db.execute("PRAGMA foreign_keys;") as cur:
                fk_row = await cur.fetchone()
                assert fk_row[0] == 1, f"Expected FK=1, got {fk_row[0]}"
            print(f"  [PASS] PRAGMA foreign_keys = {fk_row[0]} (ON)")

        # Test 3: DB file on disk
        assert DATABASE_PATH.exists(), "DB file missing from disk"
        print(f"  [PASS] Database file exists: {DATABASE_PATH}")

        # Test 4: Sync engine connection (for schema ops)
        with _sync_engine.connect() as conn:
            from sqlalchemy import text
            result = conn.execute(text("SELECT 1"))
            assert result.scalar() == 1
        print("  [PASS] Sync SQLAlchemy engine connection OK")

        print()
        print("  Stage 3 guardrail: PASSED. Async session layer is healthy.")

    except Exception as exc:
        import traceback
        print(f"  [FAIL] {exc}")
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(_run_integration_test())
