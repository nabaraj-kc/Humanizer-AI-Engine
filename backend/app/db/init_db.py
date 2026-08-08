"""
backend/app/db/init_db.py
=========================
Database initialization service for the Humanizer AI Engine.

Responsibilities:
  1. Inspect whether all required tables exist in the live database.
  2. Create any missing tables via SQLAlchemy Core metadata DDL.
  3. Seed default ApiQuota records for Google, Groq, and DeepSeek free tiers
     using an ON CONFLICT DO NOTHING (INSERT OR IGNORE) strategy to ensure
     idempotent re-runs never raise duplicate key errors.
  4. Expose a query function for inspecting seeded table states.

Free-tier quota defaults (sourced from provider documentation):
  - Google AI Studio  : 1,000,000 tokens/day, 15 RPM (Gemini Flash free tier)
  - Groq Cloud        :    14,400 tokens/day, 30 RPM (Llama 3 free tier)
  - DeepSeek          :   500,000 tokens/day, 60 RPM (DeepSeek-chat free tier)
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve project root so this module can be run directly or imported
# ---------------------------------------------------------------------------
_THIS_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parents[3]   # db -> app -> backend -> project root
sys.path.insert(0, str(_PROJECT_ROOT))

import aiosqlite
from sqlalchemy import create_engine, inspect, text as sql_text

from backend.app.db.models import metadata, api_quotas, paper_runs, text_chunks, ALL_TABLES
from backend.app.db.session import DATABASE_PATH, get_sync_engine


# ---------------------------------------------------------------------------
# Default provider seed records
# ---------------------------------------------------------------------------
DEFAULT_QUOTAS = [
    {
        "provider":    "openrouter",
        "daily_limit": 1000000,  # 1M tokens limit
        "used_today":  0,
        "rpm_limit":   20,
        "last_reset":  datetime.now(timezone.utc).isoformat(),
    },
    {
        "provider":    "google",
        "daily_limit": 1_000_000,
        "used_today":  0,
        "rpm_limit":   15,
        "last_reset":  datetime.now(timezone.utc).isoformat(),
    },
    {
        "provider":    "groq",
        "daily_limit": 14_400,
        "used_today":  0,
        "rpm_limit":   30,
        "last_reset":  datetime.now(timezone.utc).isoformat(),
    },
    {
        "provider":    "deepseek",
        "daily_limit": 500_000,
        "used_today":  0,
        "rpm_limit":   60,
        "last_reset":  datetime.now(timezone.utc).isoformat(),
    },
]


# ---------------------------------------------------------------------------
# Synchronous schema creation (SQLAlchemy Core DDL)
# ---------------------------------------------------------------------------
def create_tables_if_missing() -> list[str]:
    """
    Inspect the live database and create any tables that do not yet exist.
    Returns a list of table names that were newly created.
    """
    engine = get_sync_engine()
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    needed = set(ALL_TABLES.keys())
    missing = needed - existing

    if missing:
        # Create only the missing tables by filtering metadata
        tables_to_create = [ALL_TABLES[t] for t in missing]
        metadata.create_all(engine, tables=tables_to_create)
        return sorted(missing)
    return []


# ---------------------------------------------------------------------------
# Async seed: INSERT OR IGNORE for idempotency
# ---------------------------------------------------------------------------
async def seed_api_quotas(db: aiosqlite.Connection) -> int:
    """
    Seed default ApiQuota rows using INSERT OR IGNORE so duplicate runs
    never raise a PRIMARY KEY conflict. Returns the number of rows inserted.
    """
    inserted = 0
    for quota in DEFAULT_QUOTAS:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO api_quotas
                (provider, daily_limit, used_today, rpm_limit, last_reset)
            VALUES
                (:provider, :daily_limit, :used_today, :rpm_limit, :last_reset)
            """,
            quota,
        )
        inserted += cursor.rowcount
        # Update existing records to new limits and reset used_today counts
        await db.execute(
            """
            UPDATE api_quotas
            SET daily_limit = :daily_limit, used_today = 0
            WHERE provider = :provider
            """,
            {"daily_limit": quota["daily_limit"], "provider": quota["provider"]}
        )
    await db.commit()
    return inserted


# ---------------------------------------------------------------------------
# Main init coroutine
# ---------------------------------------------------------------------------
async def initialize_database(verbose: bool = True) -> None:
    """
    Full initialization sequence:
      1. Create missing tables via SQLAlchemy Core DDL.
      2. Seed default api_quotas records (idempotent).
      3. Verify table structures via PRAGMA table_info.
      4. Print seeded state to console.
    """
    if verbose:
        print("=== Stage 5: Database Initialization ===")
        print(f"  DB Path: {DATABASE_PATH}")
        print()

    # ── Step 1: Create tables ────────────────────────────────────────────
    newly_created = create_tables_if_missing()
    if verbose:
        if newly_created:
            for t in newly_created:
                print(f"  [CREATED] Table: {t}")
        else:
            print("  [OK] All tables already exist")

    # ── Step 2: Seed api_quotas ──────────────────────────────────────────
    async with aiosqlite.connect(str(DATABASE_PATH)) as db:
        await db.execute("PRAGMA foreign_keys = ON;")

        n_inserted = await seed_api_quotas(db)
        if verbose:
            if n_inserted > 0:
                print(f"  [SEEDED] {n_inserted} new api_quota record(s) inserted")
            else:
                print("  [OK] api_quotas already seeded (INSERT OR IGNORE skipped all)")

        # ── Step 3: PRAGMA table_info verification ───────────────────────
        if verbose:
            print()
            print("  PRAGMA table_info inspection:")
            for table_name in ["api_quotas", "paper_runs", "text_chunks"]:
                async with db.execute(f"PRAGMA table_info({table_name});") as cur:
                    cols = await cur.fetchall()
                if not cols:
                    raise RuntimeError(
                        f"PRAGMA table_info returned empty for '{table_name}' — "
                        "table may be corrupted or missing."
                    )
                col_names = [c[1] for c in cols]
                print(f"    [{table_name}] {len(cols)} columns: {col_names}")

        # ── Step 4: Print seeded api_quotas state ────────────────────────
        if verbose:
            print()
            print("  Seeded api_quotas state:")
            async with db.execute(
                "SELECT provider, daily_limit, used_today, rpm_limit FROM api_quotas"
            ) as cur:
                rows = await cur.fetchall()
            if not rows:
                raise RuntimeError("api_quotas table is empty after seeding!")
            for row in rows:
                provider, daily_limit, used_today, rpm_limit = row
                remaining = daily_limit - used_today
                print(
                    f"    {provider:<12} limit={daily_limit:>9,}  "
                    f"used={used_today:>5}  remaining={remaining:>9,}  "
                    f"rpm_limit={rpm_limit}"
                )

    if verbose:
        print()
        print("  Stage 5 guardrail: PASSED. Database initialized and seeded.")


# ---------------------------------------------------------------------------
# Query utility: inspect current table states
# ---------------------------------------------------------------------------
async def query_seeded_states() -> dict:
    """
    Query and return the current state of seeded tables as a dictionary.
    Useful for health checks and dashboard API endpoints.
    """
    result: dict = {"api_quotas": [], "paper_runs_count": 0, "text_chunks_count": 0}

    async with aiosqlite.connect(str(DATABASE_PATH)) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("SELECT * FROM api_quotas") as cur:
            rows = await cur.fetchall()
            result["api_quotas"] = [dict(r) for r in rows]

        async with db.execute("SELECT COUNT(*) FROM paper_runs") as cur:
            result["paper_runs_count"] = (await cur.fetchone())[0]

        async with db.execute("SELECT COUNT(*) FROM text_chunks") as cur:
            result["text_chunks_count"] = (await cur.fetchone())[0]

    return result


# ---------------------------------------------------------------------------
# Guardrail verification (called by Stage 5 test)
# ---------------------------------------------------------------------------
async def _run_guardrail_test() -> None:
    """
    Full guardrail sequence:
      1. Run initialize_database() — idempotent on repeated calls.
      2. Run a second time to confirm INSERT OR IGNORE handles duplicates.
      3. Query and assert all three providers are present.
      4. Confirm PRAGMA table_info returns columns for every table.
      5. Simulate corruption check: wipe and rebuild if table_info fails.
    """
    print("=== Stage 5: Compulsory Verification Guardrail ===")
    print()

    # Run 1: initial seeding
    await initialize_database(verbose=True)

    print()
    print("  --- Idempotency check (second run) ---")

    # Run 2: must not duplicate or crash
    async with aiosqlite.connect(str(DATABASE_PATH)) as db:
        n = await seed_api_quotas(db)
        assert n == 0, f"Expected 0 inserts on re-run (idempotent), got {n}"
    print("  [PASS] Second seed run: 0 duplicates inserted (INSERT OR IGNORE working)")

    # Query and validate providers
    state = await query_seeded_states()
    providers = {r["provider"] for r in state["api_quotas"]}
    for expected in ["google", "groq", "deepseek"]:
        assert expected in providers, f"Provider '{expected}' missing from api_quotas"
    print(f"  [PASS] All 3 providers present: {sorted(providers)}")

    # Validate daily limits match spec
    limits = {r["provider"]: r["daily_limit"] for r in state["api_quotas"]}
    assert limits["google"]   == 1_000_000, f"Google limit wrong: {limits['google']}"
    assert limits["groq"]     == 14_400,    f"Groq limit wrong: {limits['groq']}"
    assert limits["deepseek"] == 500_000,   f"DeepSeek limit wrong: {limits['deepseek']}"
    print(f"  [PASS] Token limits verified: google=1,000,000 | groq=14,400 | deepseek=500,000")

    # PRAGMA table_info — ensure no corruption
    async with aiosqlite.connect(str(DATABASE_PATH)) as db:
        for table_name in ["api_quotas", "paper_runs", "text_chunks"]:
            async with db.execute(f"PRAGMA table_info({table_name});") as cur:
                cols = await cur.fetchall()
            if not cols:
                print(f"  [WARN] PRAGMA table_info empty for '{table_name}' — rebuilding...")
                create_tables_if_missing()
                async with db.execute(f"PRAGMA table_info({table_name});") as cur2:
                    cols = await cur2.fetchall()
                assert cols, f"Rebuild failed for '{table_name}'"
            print(f"  [PASS] PRAGMA table_info({table_name}): {len(cols)} columns verified")

    print()
    print("  Stage 5 full guardrail: PASSED.")


if __name__ == "__main__":
    asyncio.run(_run_guardrail_test())
