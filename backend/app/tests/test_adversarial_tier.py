"""
backend/app/tests/test_adversarial_tier.py
===========================================
Local Adversarial Tier Integration & Validation Tests.
Verifies rewrite, scoring, loop controller, prompt injection, and glossary preservation.
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
import uuid
import datetime
import unittest.mock as mock
from pathlib import Path

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[3]))

from backend.app.services.loop_controller import FeedbackLoopController
from backend.app.db.session import get_async_session
from backend.app.core.websocket_manager import ws_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_adversarial_tier")


async def run_adversarial_tier_tests():
    print("=== Stage 35: Local Adversarial Tier Validation Test ===")
    print()

    run_id = str(uuid.uuid4())
    sequence_no = 1
    
    # 1. Define structured Master Summary with a 10-word technical glossary
    glossary_terms = [
        "gradient descent", "backpropagation", "hyperparameter", "transformer", 
        "attention", "semantic", "perplexity", "burstiness", "adversarial", "humanizer"
    ]
    
    dummy_summary = (
        "THESIS:\n"
        "Standard LLM academic drafts suffer from uniform perplexity and must be humanized.\n\n"
        "METHODOLOGY:\n"
        "We perform iterative loops measuring sentence variance and structural density.\n\n"
        "GLOSSARY:\n"
        f"{', '.join(glossary_terms)}"
    )

    # 2. Database preparation
    print("  --- Test Step 1: Database Initialization & Seeding ---")
    async with get_async_session() as db:
        await db.execute("DELETE FROM paper_runs WHERE run_id = :run_id", {"run_id": run_id})
        await db.execute("DELETE FROM text_chunks WHERE run_id = :run_id", {"run_id": run_id})

        # Insert paper run
        await db.execute(
            """
            INSERT INTO paper_runs (run_id, filename, total_chunks, start_time, status, master_summary)
            VALUES (:run_id, 'adversarial_test.pdf', 1, :start, 'running', :summary)
            """,
            {"run_id": run_id, "start": datetime.datetime.utcnow().isoformat(), "summary": dummy_summary}
        )
        # Insert target clean text block containing glossary terms and citation placeholder
        await db.execute(
            """
            INSERT INTO text_chunks (chunk_id, run_id, sequence_no, raw_text, clean_text, processed, iterations)
            VALUES (:chunk_id, :run_id, :seq, 'Original [4] research containing gradient descent.', 'Clean __CITATION_0__ containing gradient descent.', NULL, 0)
            """,
            {"chunk_id": str(uuid.uuid4()), "run_id": run_id, "seq": sequence_no}
        )
    print("  [PASS] Seeding completed successfully.")
    print()

    # 3. Setup Loop Controller & Mocks
    print("  --- Test Step 2: Orchestration & Mocking Configuration ---")
    controller = FeedbackLoopController()

    # Track compiled prompts
    captured_prompts = []

    async def mock_rewrite(prompt, text):
        captured_prompts.append(prompt)
        # Returns text containing preserved placeholders and glossary terms
        return "Humanized text using gradient descent and backpropagation __CITATION_0__ with high structural variance."

    scores_list = [95.0, 12.0] # baseline AI score 95% (flags), rewrite score 12% (passes)
    async def mock_detect(*args, **kwargs):
        return scores_list.pop(0) if scores_list else 10.0

    # Track websocket broadcast calls
    ws_broadcast_messages = []
    async def mock_broadcast(msg):
        ws_broadcast_messages.append(msg)

    # Apply patches
    with mock.patch.object(controller.router, "rewrite_chunk_with_failover", side_effect=mock_rewrite), \
         mock.patch.object(controller.detector, "calculate_ai_probability", side_effect=mock_detect), \
         mock.patch.object(ws_manager, "broadcast_global_message", side_effect=mock_broadcast):

        print("  --- Test Step 3: Run Feedback Loop Execution ---")
        result = await controller.humanize_chunk(
            raw_text="Original [4] research containing gradient descent.",
            clean_text="Clean __CITATION_0__ containing gradient descent.",
            run_id=run_id,
            sequence_no=sequence_no
        )

        # 4. Verify loop statistics
        assert result["success"] is True
        assert result["best_score"] == 12.0
        assert result["iterations"] == 1
        print(f"  [PASS] Humanization finished successfully. Iterations: {result['iterations']}, Best Score: {result['best_score']}%")
        print()

        # 5. Assert PromptFactory context injection
        print("  --- Test Step 4: System Prompt Context Injection Assertions ---")
        assert len(captured_prompts) == 1, "Expected rewrite engine to receive exactly 1 compiled prompt"
        compiled_prompt = captured_prompts[0]
        
        # Verify master summary thesis, methodology and glossary are present
        assert "Standard LLM academic drafts suffer from uniform perplexity" in compiled_prompt
        assert "We perform iterative loops measuring sentence variance" in compiled_prompt
        assert "gradient descent, backpropagation" in compiled_prompt
        
        # Verify placeholder instructions are present
        assert "__CITATION_IDX__" in compiled_prompt
        assert "__MATH_BLOCK_IDX__" in compiled_prompt
        print("  [PASS] Verified prompt contains Master Summary (Anti-Amnesia) context blocks.")
        print()

        # 6. Assert glossary preservation and placeholder integrity
        print("  --- Test Step 5: Glossary and Placeholder Integrity Checks ---")
        processed_text = result["processed"]
        
        # Check that citation placeholder is untouched
        assert "__CITATION_0__" in processed_text, "Placeholder must be preserved verbatim in output"
        
        # Check glossary terms preservation
        for term in ["gradient descent", "backpropagation"]:
            assert term in processed_text.lower(), f"Glossary term '{term}' must be preserved in output"
        print("  [PASS] Glossary terms and token protection walls verified intact.")
        print()

        # 7. Assert database persistence
        print("  --- Test Step 6: Database Persistence State Verification ---")
        async with get_async_session() as db:
            async with db.execute(
                "SELECT processed, iterations FROM text_chunks WHERE run_id = :run_id AND sequence_no = :seq",
                {"run_id": run_id, "seq": sequence_no}
            ) as cur:
                row = await cur.fetchone()
                
        assert row is not None
        assert row["processed"] == processed_text
        assert row["iterations"] == 1
        print("  [PASS] Verified text_chunks update committed successfully.")
        print()

        # 8. Assert WebSocket event notifications
        print("  --- Test Step 7: WebSocket Broadcast Status Verification ---")
        assert len(ws_broadcast_messages) >= 1
        # Check that progress updates were broadcast
        categories = [m.get("category") if isinstance(m, dict) else m.category for m in ws_broadcast_messages]
        states = [m.get("progress_state") if isinstance(m, dict) else m.progress_state for m in ws_broadcast_messages]
        assert "progress" in categories
        assert "rewriting" in states
        print(f"  [PASS] WebSocket notifications checked: broadcasts sent={len(ws_broadcast_messages)}.")
        print()

    # 9. DB Clean up
    async with get_async_session() as db:
        await db.execute("DELETE FROM paper_runs WHERE run_id = :run_id", {"run_id": run_id})
        await db.execute("DELETE FROM text_chunks WHERE run_id = :run_id", {"run_id": run_id})

    print("Stage 35 integration check: ALL PASSED.")


if __name__ == "__main__":
    asyncio.run(run_adversarial_tier_tests())
