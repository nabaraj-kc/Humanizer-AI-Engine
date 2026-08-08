"""
backend/app/api/stats.py
========================
Live Token Budget State API Router.
Queries quota utilization and remaining percentages across providers.
"""

# Hotpatch typing module for Python 3.11 alpha compatibility issues with Pydantic / AnyIO
import typing
if not hasattr(typing, "Required"):
    typing.Required = object
if not hasattr(typing, "NotRequired"):
    typing.NotRequired = object
if not hasattr(typing, "TypeVarTuple"):
    typing.TypeVarTuple = object
if not hasattr(typing, "Unpack"):
    typing.Unpack = object
if not hasattr(typing, "Self"):
    typing.Self = object

# Hotpatch asyncio.current_task for Python 3.11 alpha compatibility issues with anyio's cancel scope
import asyncio
import asyncio.tasks
_real_current_task = asyncio.current_task

class TaskWrapper:
    def __init__(self, task):
        self.__dict__['_task'] = task
    def __getattr__(self, name):
        if name == 'uncancel':
            return getattr(self._task, 'uncancel', lambda: getattr(self._task, '_cancelling', 0))
        if name == 'cancelling':
            return getattr(self._task, 'cancelling', lambda: getattr(self._task, '_cancelling', 0))
        return getattr(self._task, name)
    def __setattr__(self, name, value):
        setattr(self._task, name, value)
    @property
    def __class__(self):
        return self._task.__class__
    def __eq__(self, other):
        if isinstance(other, TaskWrapper):
            return self._task is other._task
        return self._task is other
    def __hash__(self):
        return hash(self._task)

def wrapped_current_task(loop=None):
    t = _real_current_task(loop)
    if t is None:
        return None
    if isinstance(t, TaskWrapper):
        return t
    if hasattr(t, "_wrapper"):
        return t._wrapper
    
    wrapper = TaskWrapper(t)
    try:
        t._wrapper = wrapper
    except Exception:
        pass
    return wrapper

asyncio.current_task = wrapped_current_task
asyncio.tasks.current_task = wrapped_current_task

import logging
import sys
from pathlib import Path
from fastapi import APIRouter
from pydantic import BaseModel, Field

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[3]))

from backend.app.db.session import get_async_session

logger = logging.getLogger("humanizer_stats")

router = APIRouter()

# Default fallback configurations matching settings
DEFAULT_QUOTAS = {
    "openrouter": {"daily_limit": 1000000, "used_today": 0, "rpm_limit": 20},
    "google": {"daily_limit": 1000000, "used_today": 0, "rpm_limit": 15},
    "groq": {"daily_limit": 14400, "used_today": 0, "rpm_limit": 30},
    "deepseek": {"daily_limit": 500000, "used_today": 0, "rpm_limit": 60},
}


# ---------------------------------------------------------------------------
# API Schemas
# ---------------------------------------------------------------------------

class ProviderStats(BaseModel):
    provider: str
    daily_limit: int
    used_today: int
    remaining: int
    remaining_percentage: float
    rpm_limit: int


class TokenStatsResponse(BaseModel):
    status: str
    providers: list[ProviderStats]


# ---------------------------------------------------------------------------
# Endpoint Routing
# ---------------------------------------------------------------------------

@router.get("/api/stats/tokens", response_model=TokenStatsResponse)
async def get_token_stats():
    """
    Retrieves current daily token budget consumption metrics for all AI providers.
    Calculates used vs remaining percentages, falling back to default values
    if database records are missing or corrupted.
    """
    providers_data = {}

    try:
        async with get_async_session() as db:
            async with db.execute(
                "SELECT provider, daily_limit, used_today, rpm_limit FROM api_quotas"
            ) as cur:
                rows = await cur.fetchall()
                for row in rows:
                    providers_data[row["provider"]] = {
                        "daily_limit": row["daily_limit"],
                        "used_today": row["used_today"],
                        "rpm_limit": row["rpm_limit"]
                    }
    except Exception as e:
        logger.error(f"Failed to query database for api_quotas: {e}. Falling back to default configs.")

    final_providers = []
    # Loop over standard supported providers
    for name in ["openrouter", "google", "groq", "deepseek"]:
        if name in providers_data:
            p_data = providers_data[name]
        else:
            logger.warning(f"Quota record for {name} missing. Applying fallback defaults.")
            p_data = DEFAULT_QUOTAS[name]

        daily_limit = p_data["daily_limit"]
        used_today = p_data["used_today"]
        rpm_limit = p_data["rpm_limit"]

        remaining = max(0, daily_limit - used_today)
        remaining_percentage = (remaining / daily_limit * 100.0) if daily_limit > 0 else 0.0

        final_providers.append(
            ProviderStats(
                provider=name,
                daily_limit=daily_limit,
                used_today=used_today,
                remaining=remaining,
                remaining_percentage=round(remaining_percentage, 2),
                rpm_limit=rpm_limit
            )
        )

    return TokenStatsResponse(status="success", providers=final_providers)


# ---------------------------------------------------------------------------
# Document Runs History Endpoint
# ---------------------------------------------------------------------------

@router.get("/api/runs")
async def list_runs():
    """
    Returns list of all document processing runs from the database,
    ordered by most recent first. Used by the frontend documents history panel.
    """
    try:
        async with get_async_session() as db:
            async with db.execute(
                """
                SELECT run_id, filename, total_chunks, start_time, status
                FROM paper_runs
                ORDER BY start_time DESC
                LIMIT 50
                """
            ) as cur:
                rows = await cur.fetchall()
                runs = []
                for row in rows:
                    runs.append({
                        "run_id": row["run_id"],
                        "filename": row["filename"],
                        "total_chunks": row["total_chunks"],
                        "start_time": row["start_time"],
                        "status": row["status"],
                    })
        return {"status": "success", "runs": runs}
    except Exception as e:
        logger.error(f"Failed to query paper_runs for history listing: {e}")
        return {"status": "error", "runs": [], "message": str(e)}


# ---------------------------------------------------------------------------
# Stage 20 Verification Guardrail Test
# ---------------------------------------------------------------------------

def run_tests() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import asyncio

    print("=== Stage 20: Live Token Budget State Endpoint Verification ===")
    print()

    # Setup local test app
    test_app = FastAPI()
    test_app.include_router(router)
    client = TestClient(test_app)

    # 1. Seed test database values to verify connection and math calculations
    print("  --- Test 1: Math validation with seeded DB records ---")
    
    async def seed_test_quotas():
        async with get_async_session() as db:
            # First, clean existing test rows to avoid conflicts
            await db.execute("DELETE FROM api_quotas WHERE provider IN ('google', 'groq', 'deepseek', 'openrouter')")
            # Seed custom test values:
            # Google: 1,000,000 limit, 400,000 used -> 600,000 (60%) remaining
            # Groq: 10,000 limit, 2,500 used -> 7,500 (75%) remaining
            # DeepSeek: 100,000 limit, 100,000 used -> 0 (0%) remaining
            # OpenRouter: 1,000,000 limit, 100,000 used -> 900,000 (90%) remaining
            await db.execute(
                """
                INSERT INTO api_quotas (provider, daily_limit, used_today, rpm_limit, last_reset)
                VALUES 
                  ('google', 1000000, 400000, 15, '2026-06-15T00:00:00'),
                  ('groq', 10000, 2500, 30, '2026-06-15T00:00:00'),
                  ('deepseek', 100000, 100000, 60, '2026-06-15T00:00:00'),
                  ('openrouter', 1000000, 100000, 20, '2026-06-15T00:00:00')
                """
            )

    asyncio.run(seed_test_quotas())

    # Trigger endpoint
    response = client.get("/api/stats/tokens")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data["status"] == "success"
    
    providers = {p["provider"]: p for p in data["providers"]}
    assert len(providers) == 4
    
    # Assert exact math outputs
    assert providers["google"]["remaining"] == 600000
    assert providers["google"]["remaining_percentage"] == 60.0
    assert providers["groq"]["remaining"] == 7500
    assert providers["groq"]["remaining_percentage"] == 75.0
    assert providers["deepseek"]["remaining"] == 0
    assert providers["deepseek"]["remaining_percentage"] == 0.0
    assert providers["openrouter"]["remaining"] == 900000
    assert providers["openrouter"]["remaining_percentage"] == 90.0
    
    print("  [PASS] Custom database seed values parsed and matched mathematical bounds.")
    print()

    # 2. Test fallback logic when database lacks records
    print("  --- Test 2: Database zero-records fallback check ---")
    
    async def clear_quotas():
        async with get_async_session() as db:
            await db.execute("DELETE FROM api_quotas WHERE provider IN ('google', 'groq', 'deepseek', 'openrouter')")

    asyncio.run(clear_quotas())

    # Call endpoint again - should succeed and match settings default configurations
    response_fb = client.get("/api/stats/tokens")
    assert response_fb.status_code == 200
    data_fb = response_fb.json()
    
    providers_fb = {p["provider"]: p for p in data_fb["providers"]}
    assert providers_fb["google"]["daily_limit"] == 1000000
    assert providers_fb["google"]["used_today"] == 0
    assert providers_fb["google"]["remaining_percentage"] == 100.0
    assert providers_fb["groq"]["daily_limit"] == 14400
    assert providers_fb["deepseek"]["daily_limit"] == 500000
    print("  [PASS] Endpoint cleanly fell back to configuration defaults without throwing errors.")
    print()

    # Re-seed default DB states to restore clean environment state
    async def restore_defaults():
        async with get_async_session() as db:
            await db.execute("DELETE FROM api_quotas WHERE provider IN ('google', 'groq', 'deepseek', 'openrouter')")
            await db.execute(
                """
                INSERT INTO api_quotas (provider, daily_limit, used_today, rpm_limit, last_reset)
                VALUES 
                  ('google', 1000000, 0, 15, '2026-06-15T00:00:00'),
                  ('groq', 14400, 0, 30, '2026-06-15T00:00:00'),
                  ('deepseek', 500000, 0, 60, '2026-06-15T00:00:00'),
                  ('openrouter', 1000000, 0, 20, '2026-06-15T00:00:00')
                """
            )
            
    asyncio.run(restore_defaults())
    print("Stage 20 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
