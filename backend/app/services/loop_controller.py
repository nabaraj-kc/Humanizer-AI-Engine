"""
backend/app/services/loop_controller.py
======================================
The Iterative Feedback Control Loop.
Links rewriting router and adversarial detector to execute rewrite-and-score loops.
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
import re
import sys
from pathlib import Path

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[3]))

from backend.app.services.api_router import WaterfallRouter
from backend.app.services.detector_fallback import AdversarialDetectorRouter
from backend.app.services.prompt_factory import PromptFactory
from backend.app.services.convergence_analyzer import ConvergenceAnalyzer
from backend.app.core.websocket_manager import ws_manager
from backend.app.db.session import get_async_session

logger = logging.getLogger("humanizer_loop_controller")


class FeedbackLoopController:
    """
    Coordinates the rewrite-and-score loops for individual text chunks.
    Ensures safe early exiting when threshold is passed, tracks iteration limits,
    and updates database and WebSockets progress.
    """

    def __init__(self):
        self.router = WaterfallRouter()
        self.detector = AdversarialDetectorRouter()
        self.prompt_factory = PromptFactory()
        self.analyzer = ConvergenceAnalyzer()

    def validate_placeholders(self, original_text: str, rewritten_text: str) -> bool:
        """
        Verify that all protected formatting placeholders (e.g. __CITATION_0__, __MATH_BLOCK_1__)
        present in original_text are preserved verbatim in rewritten_text.
        """
        placeholders = re.findall(r'__[A-Z0-9_]+__', original_text)
        for p in placeholders:
            if p not in rewritten_text:
                logger.warning(f"Placeholder protection wall breached! Missing placeholder '{p}' in rewrite.")
                return False
        return True

    async def humanize_chunk(
        self,
        raw_text: str,
        clean_text: str,
        run_id: str,
        sequence_no: int,
        client_id: str = None
    ) -> dict:
        """
        Executes the iterative rewrite and score loop on a single text chunk.
        """
        logger.info(f"Starting humanization loop for run_id={run_id}, chunk={sequence_no}")
        
        # 1. Check if master summary is ready and compile prompt
        try:
            system_prompt = await self.prompt_factory.compile_system_prompt(run_id)
        except Exception as e:
            logger.error(f"Failed to compile system prompt for run_id={run_id}: {e}")
            raise

        # 2. Get baseline AI score
        baseline_score = await self.detector.calculate_ai_probability(clean_text)
        logger.info(f"Baseline AI score for chunk {sequence_no}: {baseline_score}%")

        scores_history = [baseline_score]
        best_text = clean_text
        best_score = baseline_score
        current_text = clean_text

        # 3. If baseline score is already human enough (< 15%), skip looping (only if not using statistical fallback)
        if baseline_score < 15.0 and not self.detector.using_fallback:
            logger.info(f"Baseline score {baseline_score}% is already below 15.0%. Skipping loop.")
        else:
            best_rewritten_text = None
            best_rewritten_score = 999.0

            # Loop up to 3 times
            for iteration in range(1, 4):
                logger.info(f"Executing rewrite iteration {iteration}/3 for chunk {sequence_no}...")
                
                # Broadcast websocket update
                await ws_manager.broadcast_global_message({
                    "category": "progress",
                    "progress_state": "rewriting",
                    "token_updates": {"google": 0, "groq": 0, "deepseek": 0}
                })

                try:
                    # Rewrite via router
                    rewritten = await self.router.rewrite_chunk_with_failover(system_prompt, current_text)
                    
                    # Validate placeholders to prevent data loss
                    if not self.validate_placeholders(clean_text, rewritten):
                        logger.warning(f"Placeholder validation failed. Rejecting iteration {iteration} text.")
                        # Do not count this iteration's score, but still track attempts
                        continue

                    # Score rewritten text
                    new_score = await self.detector.calculate_ai_probability(rewritten)
                    scores_history.append(new_score)
                    
                    logger.info(f"Iteration {iteration} score: {new_score}% (Previous: {best_score}%)")

                    # Track best rewritten text across loops
                    if new_score < best_rewritten_score:
                        best_rewritten_score = new_score
                        best_rewritten_text = rewritten

                    # Update best score/text if improved
                    if new_score < best_score:
                        best_score = new_score
                        best_text = rewritten

                    # Early exit check
                    if new_score < 15.0:
                        logger.info(f"Early exit: score {new_score}% is below 15.0% threshold.")
                        break

                    # Convergence check to adjust prompt or stop loop early
                    if iteration < 3:
                        should_stop, adjusted_prompt = self.analyzer.analyze_convergence(scores_history, system_prompt)
                        if should_stop:
                            logger.info("Halting rewrite loop due to convergence analyzer stopping condition.")
                            break
                        system_prompt = adjusted_prompt
                        current_text = rewritten

                except Exception as loop_err:
                    logger.error(f"Error in rewrite loop iteration {iteration}: {loop_err}")
                    # Continue loop in case next iteration succeeds or fallback behaves better

            # Fallback check: if detector fallback is active, prevent reverting to clean text
            if self.detector.using_fallback and best_rewritten_text is not None:
                if best_text == clean_text:
                    logger.info("Detector is in fallback mode. Returning the best rewritten text instead of unmodified baseline text.")
                    best_text = best_rewritten_text
                    best_score = best_rewritten_score

        # 4. Save best text version & iteration count to database
        total_iterations_run = len(scores_history) - 1
        logger.info(f"Loop finished. Best score: {best_score}%. Total iterations: {total_iterations_run}. Saving to DB...")

        async with get_async_session() as db:
            await db.execute(
                """
                UPDATE text_chunks
                SET processed = :processed, iterations = :iterations
                WHERE run_id = :run_id AND sequence_no = :sequence_no
                """,
                {
                    "processed": best_text,
                    "iterations": total_iterations_run,
                    "run_id": run_id,
                    "sequence_no": sequence_no
                }
            )

        return {
            "success": True,
            "raw_text": raw_text,
            "clean_text": clean_text,
            "processed": best_text,
            "best_score": best_score,
            "iterations": total_iterations_run,
            "scores_history": scores_history
        }


# ---------------------------------------------------------------------------
# Stage 32 Verification Guardrail Tests
# ---------------------------------------------------------------------------
def run_tests() -> None:
    print("=== Stage 32: Feedback Loop Controller Verification ===")
    print()

    import datetime
    import uuid
    import unittest.mock as mock

    controller = FeedbackLoopController()
    run_id = str(uuid.uuid4())
    sequence_no = 0

    dummy_summary = (
        "THESIS:\nCore thesis statement.\n\n"
        "METHODOLOGY:\nResearch methodology description.\n\n"
        "GLOSSARY:\nTerm1, Term2, Term3, Term4, Term5, Term6, Term7, Term8, Term9, Term10"
    )

    async def setup_db():
        async with get_async_session() as db:
            # Clean up old records
            await db.execute("DELETE FROM paper_runs WHERE run_id = :run_id", {"run_id": run_id})
            await db.execute("DELETE FROM text_chunks WHERE run_id = :run_id", {"run_id": run_id})
            
            # Create paper run
            await db.execute(
                """
                INSERT INTO paper_runs (run_id, filename, total_chunks, start_time, status, master_summary)
                VALUES (:run_id, 'test_loop.pdf', 1, :start, 'running', :summary)
                """,
                {"run_id": run_id, "start": datetime.datetime.utcnow().isoformat(), "summary": dummy_summary}
            )
            # Create text chunk
            await db.execute(
                """
                INSERT INTO text_chunks (chunk_id, run_id, sequence_no, raw_text, clean_text, processed, iterations)
                VALUES (:chunk_id, :run_id, :seq, 'Raw [1] text.', 'Clean __CITATION_0__ text.', NULL, 0)
                """,
                {"chunk_id": str(uuid.uuid4()), "run_id": run_id, "seq": sequence_no}
            )

    asyncio.run(setup_db())

    # 1. Test Case: Baseline already below threshold (< 15%)
    print("  --- Test 1: Skip looping when baseline score is below threshold ---")
    async def mock_detect_low(*args, **kwargs):
        return 10.0

    with mock.patch.object(controller.detector, "calculate_ai_probability", side_effect=mock_detect_low):
        res = asyncio.run(controller.humanize_chunk(
            raw_text="Raw [1] text.",
            clean_text="Clean __CITATION_0__ text.",
            run_id=run_id,
            sequence_no=sequence_no
        ))
        assert res["iterations"] == 0
        assert res["best_score"] == 10.0
        assert res["processed"] == "Clean __CITATION_0__ text."
        print("  [PASS] Correctly skipped looping for baseline score < 15.0%.")
        print()

    # 2. Test Case: Normal loop execution with early exit (< 15%)
    print("  --- Test 2: Standard loop execution with early exit ---")
    
    # We mock rewriting to return text with placeholder intact
    async def mock_rewrite_ok(prompt, text):
        return f"{text} (rewritten)"

    # Scores: baseline=80%, iter 1=40%, iter 2=10% (under 15% -> exits)
    scores_q = [80.0, 40.0, 10.0]
    async def mock_detect_scores(*args, **kwargs):
        return scores_q.pop(0) if scores_q else 5.0

    # Reset scores list for the next runs
    scores_q = [80.0, 40.0, 10.0]

    with mock.patch.object(controller.router, "rewrite_chunk_with_failover", side_effect=mock_rewrite_ok), \
         mock.patch.object(controller.detector, "calculate_ai_probability", side_effect=mock_detect_scores):
        res = asyncio.run(controller.humanize_chunk(
            raw_text="Raw [1] text.",
            clean_text="Clean __CITATION_0__ text.",
            run_id=run_id,
            sequence_no=sequence_no
        ))
        assert res["iterations"] == 2
        assert res["best_score"] == 10.0
        assert "__CITATION_0__" in res["processed"]
        print(f"  [PASS] Early exited after {res['iterations']} iterations. Best score: {res['best_score']}%")
        print()

    # 3. Test Case: Max iteration limit execution
    print("  --- Test 3: Loops terminate after maximum iteration limit of 3 ---")
    scores_q_max = [90.0, 80.0, 75.0, 70.0] # baseline + 3 iterations
    async def mock_detect_scores_max(*args, **kwargs):
        return scores_q_max.pop(0) if scores_q_max else 60.0

    with mock.patch.object(controller.router, "rewrite_chunk_with_failover", side_effect=mock_rewrite_ok), \
         mock.patch.object(controller.detector, "calculate_ai_probability", side_effect=mock_detect_scores_max):
        res = asyncio.run(controller.humanize_chunk(
            raw_text="Raw [1] text.",
            clean_text="Clean __CITATION_0__ text.",
            run_id=run_id,
            sequence_no=sequence_no
        ))
        assert res["iterations"] == 3
        assert res["best_score"] == 70.0
        print("  [PASS] Loops correctly capped at max 3 iterations, keeping best score.")
        print()

    # 4. Test Case: Placeholder validation guardrail
    print("  --- Test 4: Placeholder validation guardrail rejects bad rewrites ---")
    
    async def mock_rewrite_bad(prompt, text):
        return "Clean text completely missing the citation placeholder."

    scores_q_bad = [90.0, 10.0] # If accepted, would exit early on 10%
    async def mock_detect_scores_bad(*args, **kwargs):
        return scores_q_bad.pop(0) if scores_q_bad else 10.0

    with mock.patch.object(controller.router, "rewrite_chunk_with_failover", side_effect=mock_rewrite_bad), \
         mock.patch.object(controller.detector, "calculate_ai_probability", side_effect=mock_detect_scores_bad):
        res = asyncio.run(controller.humanize_chunk(
            raw_text="Raw [1] text.",
            clean_text="Clean __CITATION_0__ text.",
            run_id=run_id,
            sequence_no=sequence_no
        ))
        # Since rewritten text is rejected, it should keep the baseline clean text as the best
        # and execute iterations without accepting the text.
        assert res["processed"] == "Clean __CITATION_0__ text."
        assert res["best_score"] == 90.0
        print("  [PASS] Placeholder protection successfully caught bad output and rejected changes.")
        print()

    # Cleanup DB
    async def cleanup():
        async with get_async_session() as db:
            await db.execute("DELETE FROM paper_runs WHERE run_id = :run_id", {"run_id": run_id})
            await db.execute("DELETE FROM text_chunks WHERE run_id = :run_id", {"run_id": run_id})

    asyncio.run(cleanup())
    print("Stage 32 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
