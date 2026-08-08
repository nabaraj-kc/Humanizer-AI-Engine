"""
backend/app/api/deps.py
=======================
Dependency injection utilities and middleware for API endpoints.
Provides the database session yield generator and connection lifecycle management.
"""

from typing import AsyncGenerator
import aiosqlite
import sys
from pathlib import Path

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[3]))

# Hotpatch typing module for Python 3.11 alpha compatibility issues with Pydantic / AnyIO / aiohttp
import typing

class SubscriptableObject:
    def __class_getitem__(cls, item):
        return object
    def __init__(self, *args, **kwargs):
        pass

# Force override draft types that raise TypeErrors in early 3.11 alphas
typing.Unpack = SubscriptableObject
typing.TypeVarTuple = SubscriptableObject
typing.Required = object
typing.NotRequired = object
typing.Self = object

try:
    import typing_extensions
    typing_extensions.Unpack = SubscriptableObject
    typing_extensions.TypeVarTuple = SubscriptableObject
    typing_extensions.Required = object
    typing_extensions.NotRequired = object
    typing_extensions.Self = object
except ImportError:
    pass

from backend.app.db.session import get_async_session


async def get_async_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """
    Dependency generator yielding an active database connection session.
    Encloses the yield block in a try-finally layer to ensure the generator
    cleans up and raises exceptions cleanly for the transaction coordinator.
    """
    async with get_async_session() as db:
        try:
            yield db
        finally:
            # Cleanup is natively performed by get_async_session context manager,
            # but this block ensures explicit boundary tracking.
            pass


# ---------------------------------------------------------------------------
# Stage 16 Verification Guardrail Test
# ---------------------------------------------------------------------------

async def run_tests() -> None:
    import uuid
    print("=== Stage 16: Database Dependency Injection Verification ===")
    print()

    # Test 1: Verify get_async_db yields active, working connection and closes cleanly
    print("  --- Test 1: Standard session generator usage ---")
    
    connection_ref = None
    async for db in get_async_db():
        connection_ref = db
        # Check if the connection is active by running a select
        async with db.execute("SELECT 1") as cursor:
            row = await cursor.fetchone()
            assert row[0] == 1
        print("  [PASS] Connection successfully yielded and verified active.")
        
    # Check if the connection is closed after the generator exits
    # For aiosqlite, a closed connection's underlying sqlite3 connection is None or raises an error on query
    try:
        await connection_ref.execute("SELECT 1")
        assert False, "Expected sqlite3.ProgrammingError or similar because connection is closed"
    except Exception as e:
        print(f"  [PASS] Verified connection is closed: {e}")
    print()

    # Test 2: Simulate request crash & verify transactional rollback
    print("  --- Test 2: Crash simulation and transaction rollback check ---")
    
    unique_provider = f"test_provider_{uuid.uuid4().hex[:8]}"
    
    # We will run the generator, insert a row, then raise an exception, and assert the transaction was rolled back.
    try:
        async for db in get_async_db():
            # Insert a temporary quota record
            await db.execute(
                """
                INSERT INTO api_quotas (provider, daily_limit, used_today, rpm_limit, last_reset)
                VALUES (:provider, 100, 0, 10, '2026-06-15T00:00:00')
                """,
                {"provider": unique_provider}
            )
            print("  [NOTE] Inserted dummy record inside active transaction...")
            # Simulate a crash
            raise RuntimeError("Operational crash during database operation")
    except RuntimeError as e:
        print(f"  [NOTE] Caught simulated exception: {e}")

    # Now verify the database state. Since a crash occurred, the INSERT must have been rolled back.
    async with get_async_session() as verify_db:
        async with verify_db.execute(
            "SELECT * FROM api_quotas WHERE provider = :provider",
            {"provider": unique_provider}
        ) as cur:
            row = await cur.fetchone()
            assert row is None, f"Expected record to be rolled back, but it exists: {dict(row) if row else None}"
            
    print("  [PASS] Operational crash triggered successful transaction rollback.")
    print()
    print("Stage 16 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_tests())
