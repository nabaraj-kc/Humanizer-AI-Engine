"""
backend/app/services/batch_manager.py
=====================================
Multi-Threaded (Asynchronous) Batch Processing Manager.
Concurrently executes rewrite/score loops across multiple text chunks with limit and isolation.
"""

# Hotpatch typing module for Python 3.11 alpha compatibility issues with Pydantic / AnyIO / aiohttp
import typing
if not hasattr(typing, "Required"):
    typing.Required = object
if not hasattr(typing, "NotRequired"):
    typing.NotRequired = object
if not hasattr(typing, "TypeVarTuple"):
    class DummyTypeVarTuple:
        def __init__(self, *args, **kwargs):
            pass
    typing.TypeVarTuple = DummyTypeVarTuple
if not hasattr(typing, "Unpack"):
    class SubscriptableObject:
        def __class_getitem__(cls, item):
            return object
    typing.Unpack = SubscriptableObject
if not hasattr(typing, "Self"):
    typing.Self = object

# Hotpatch asyncio.Timeout for aiohttp compatibility in Python 3.11 alpha
import asyncio
if not hasattr(asyncio, "Timeout"):
    class Timeout:
        def __init__(self, deadline):
            self.deadline = deadline
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def when(self):
            return self.deadline
        def reschedule(self, when):
            self.deadline = when
        def expired(self):
            return False
    asyncio.Timeout = Timeout

# Hotpatch asyncio.current_task for Python 3.11 alpha compatibility issues with anyio's cancel scope
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

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[3]))

from backend.app.services.loop_controller import FeedbackLoopController

logger = logging.getLogger("humanizer_batch_manager")


class BatchProcessingManager:
    """
    Manages concurrent, rate-limited processing of text chunks.
    Guarantees isolation of crashes: failing chunks do not halt the rest of the batch.
    """

    def __init__(self, max_concurrency: int = 3):
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.controller = FeedbackLoopController()

    async def _process_single_chunk_with_semaphore(
        self,
        chunk: dict,
        run_id: str,
        client_id: str = None
    ) -> dict:
        """
        Wrapper running a single chunk process constrained by the concurrency semaphore.
        Catches and isolates exceptions to prevent cascading failure.
        """
        seq = chunk.get("sequence_no", 0)
        async with self.semaphore:
            logger.info(f"Concurrency lock acquired for chunk sequence_no={seq}")
            try:
                result = await self.controller.humanize_chunk(
                    raw_text=chunk.get("raw_text", ""),
                    clean_text=chunk.get("clean_text", ""),
                    run_id=run_id,
                    sequence_no=seq,
                    client_id=client_id
                )
                return result
            except Exception as e:
                logger.error(f"Error isolated on chunk sequence_no={seq}: {e}", exc_info=True)
                return {
                    "success": False,
                    "sequence_no": seq,
                    "raw_text": chunk.get("raw_text", ""),
                    "clean_text": chunk.get("clean_text", ""),
                    "processed": chunk.get("clean_text", ""),
                    "best_score": 100.0,
                    "iterations": 0,
                    "error": str(e)
                }

    async def process_chunks_batch(
        self,
        chunks: list[dict],
        run_id: str,
        client_id: str = None
    ) -> list[dict]:
        """
        Processes an array of chunks concurrently, capped at max_concurrency workers.
        """
        if not chunks:
            return []

        logger.info(f"Batch execution scheduled for {len(chunks)} chunks under run_id={run_id}")
        tasks = [
            self._process_single_chunk_with_semaphore(chunk, run_id, client_id)
            for chunk in chunks
        ]
        results = await asyncio.gather(*tasks)
        logger.info(f"Batch execution finished for run_id={run_id}. Total results: {len(results)}")
        return list(results)


# ---------------------------------------------------------------------------
# Stage 34 Verification Guardrail Tests
# ---------------------------------------------------------------------------
def run_tests() -> None:
    print("=== Stage 34: Multi-Threaded Batch Processing Manager Verification ===")
    print()

    import datetime
    import uuid
    import unittest.mock as mock
    from backend.app.db.session import get_async_session

    manager = BatchProcessingManager(max_concurrency=2)  # Cap at 2 for testing
    run_id = str(uuid.uuid4())

    dummy_summary = (
        "THESIS:\nCore thesis statement.\n\n"
        "METHODOLOGY:\nResearch methodology description.\n\n"
        "GLOSSARY:\nTerm1, Term2, Term3, Term4, Term5, Term6, Term7, Term8, Term9, Term10"
    )

    async def setup_db():
        async with get_async_session() as db:
            await db.execute("DELETE FROM paper_runs WHERE run_id = :run_id", {"run_id": run_id})
            await db.execute("DELETE FROM text_chunks WHERE run_id = :run_id", {"run_id": run_id})
            
            await db.execute(
                """
                INSERT INTO paper_runs (run_id, filename, total_chunks, start_time, status, master_summary)
                VALUES (:run_id, 'batch_test.pdf', 3, :start, 'running', :summary)
                """,
                {"run_id": run_id, "start": datetime.datetime.utcnow().isoformat(), "summary": dummy_summary}
            )
            for seq in range(3):
                await db.execute(
                    """
                    INSERT INTO text_chunks (chunk_id, run_id, sequence_no, raw_text, clean_text, processed, iterations)
                    VALUES (:chunk_id, :run_id, :seq, :raw, :clean, NULL, 0)
                    """,
                    {
                        "chunk_id": str(uuid.uuid4()),
                        "run_id": run_id,
                        "seq": seq,
                        "raw": f"Raw content {seq}",
                        "clean": f"Clean content {seq}"
                    }
                )

    asyncio.run(setup_db())

    # Mock loop controller to log timings to check concurrency execution limit
    running_tasks_count = 0
    max_observed_concurrency = 0

    async def mock_humanize(raw_text, clean_text, run_id, sequence_no, client_id=None):
        nonlocal running_tasks_count, max_observed_concurrency
        running_tasks_count += 1
        max_observed_concurrency = max(max_observed_concurrency, running_tasks_count)
        
        # Simulate simulated network delay to verify overlap
        await asyncio.sleep(0.1)
        
        running_tasks_count -= 1
        
        # If it is chunk 1, raise an intentional exception to verify isolation
        if sequence_no == 1:
            raise RuntimeError("Chunk 1 failed intentionally")
            
        return {
            "success": True,
            "sequence_no": sequence_no,
            "processed": f"Humanized content {sequence_no}",
            "best_score": 12.0,
            "iterations": 1
        }

    test_chunks = [
        {"sequence_no": 0, "raw_text": "Raw content 0", "clean_text": "Clean content 0"},
        {"sequence_no": 1, "raw_text": "Raw content 1", "clean_text": "Clean content 1"},
        {"sequence_no": 2, "raw_text": "Raw content 2", "clean_text": "Clean content 2"},
    ]

    with mock.patch.object(manager.controller, "humanize_chunk", side_effect=mock_humanize):
        results = asyncio.run(manager.process_chunks_batch(test_chunks, run_id))
        
        # Verify total results count
        assert len(results) == 3
        
        # Verify concurrency constraint (was capped at 2)
        assert max_observed_concurrency <= 2
        print(f"  [PASS] Concurrency limit verified. Max observed parallel workers: {max_observed_concurrency}")

        # Verify crash isolation: chunk 0 & 2 succeeded, chunk 1 returned fail dict but didn't crash batch
        assert results[0]["success"] is True
        assert results[2]["success"] is True
        assert results[1]["success"] is False
        assert "failed intentionally" in results[1]["error"]
        print("  [PASS] Individual crash isolation guardrail verified. Stalled chunks bypassed safely.")
        print()

    # Cleanup DB records
    async def cleanup():
        async with get_async_session() as db:
            await db.execute("DELETE FROM paper_runs WHERE run_id = :run_id", {"run_id": run_id})
            await db.execute("DELETE FROM text_chunks WHERE run_id = :run_id", {"run_id": run_id})

    asyncio.run(cleanup())
    print("Stage 34 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
