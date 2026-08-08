"""
backend/app/services/convergence_analyzer.py
============================================
Mathematical Convergence Diagnostic Analyzer.
Tracks scoring progression across loops, triggers early stop on degradation or stall.
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

logger = logging.getLogger("humanizer_convergence_analyzer")


class ConvergenceAnalyzer:
    """
    Analyzes historical scoring updates across iterations.
    Detects if performance improvements have stalled or degraded,
    returning early stop signals or injecting corrective rewrite instructions.
    """

    def __init__(self, stall_threshold: float = 2.0):
        self.stall_threshold = stall_threshold

    def analyze_convergence(self, scores: list[float], current_prompt: str) -> tuple[bool, str]:
        """
        Evaluates a list of consecutive AI probability scores (0.0 to 100.0).
        Returns:
          should_stop: bool - True if the loop should be aborted early
          adjusted_prompt: str - The prompt with appended correction instructions if needed
        """
        if len(scores) < 2:
            return False, current_prompt

        latest_score = scores[-1]
        prev_score = scores[-2]

        logger.info(f"Convergence check: previous={prev_score}%, latest={latest_score}%")

        # 1. Degradation check: if score gets significantly worse (by more than 5%), stop looping
        # A small tolerance is used to avoid halting on minor statistical noise from fallback detectors.
        DEGRADATION_TOLERANCE = 5.0
        if latest_score > prev_score + DEGRADATION_TOLERANCE:
            logger.warning(f"Significant degradation detected: score increased from {prev_score}% to {latest_score}% (>+{DEGRADATION_TOLERANCE}%). Halting loop.")
            return True, current_prompt

        # 2. Stall check: if improvement is less than the threshold
        improvement = prev_score - latest_score
        if improvement < self.stall_threshold:
            logger.info(f"Improvement of {improvement:.2f}% is below threshold of {self.stall_threshold}%.")
            
            # If corrective instructions were already injected, and it still stalled, we stop looping
            if "STALLING CORRECTIVE INSTRUCTION" in current_prompt:
                logger.warning("Score stalled twice in a row despite corrective prompt. Halting loop.")
                return True, current_prompt

            # Inject corrective instructions to demand aggressive rewriting
            corrective_instruction = (
                "\n\n=== STALLING CORRECTIVE INSTRUCTION ===\n"
                "CRITICAL: The humanization scoring has stalled. The previous rewrite did not reduce the AI detection probability sufficiently.\n"
                "You must apply MORE AGGRESSIVE changes: restructure the sentences completely, vary the sentence lengths more drastically, "
                "prefer synonyms that reduce predictability, and replace common robotic AI patterns with rare synonyms while preserving protected tokens exactly."
            )
            adjusted_prompt = current_prompt + corrective_instruction
            logger.info("Scoring stalled. Injected corrective humanization instructions into rewrite prompt.")
            return False, adjusted_prompt

        # 3. Continuous progress: keep loop active
        return False, current_prompt


# ---------------------------------------------------------------------------
# Stage 33 Verification Guardrail Tests
# ---------------------------------------------------------------------------
def run_tests() -> None:
    print("=== Stage 33: Convergence Analyzer Verification ===")
    print()

    analyzer = ConvergenceAnalyzer(stall_threshold=2.0)
    base_prompt = "Rewrite this text chunk safely."

    # Test 1: Single score (no convergence check possible yet)
    print("  --- Test 1: Single score check ---")
    stop, prompt = analyzer.analyze_convergence([90.0], base_prompt)
    assert not stop
    assert prompt == base_prompt
    print("  [PASS] Single score returned False (no-stop) and unmodified prompt.")
    print()

    # Test 2: Degradation check (score gets worse)
    print("  --- Test 2: Degradation check ---")
    # Score went from 60% to 75% (higher AI probability = worse)
    stop, prompt = analyzer.analyze_convergence([60.0, 75.0], base_prompt)
    assert stop
    assert prompt == base_prompt
    print("  [PASS] Score degradation successfully triggered immediate stop.")
    print()

    # Test 3: Stall check (first stall)
    print("  --- Test 3: First stall prompt adjustment check ---")
    # Score went from 50% to 49% (improvement of 1.0% is < 2.0% threshold)
    stop, prompt = analyzer.analyze_convergence([50.0, 49.0], base_prompt)
    assert not stop
    assert "STALLING CORRECTIVE INSTRUCTION" in prompt
    print("  [PASS] First score stall correctly injected corrective instructions.")
    print()

    # Test 4: Second stall check (stop looping)
    print("  --- Test 4: Second stall check (halt loop) ---")
    stalled_prompt = base_prompt + "\n\n=== STALLING CORRECTIVE INSTRUCTION ===\n..."
    # Score went from 49% to 48% (improvement of 1.0% again)
    stop, prompt = analyzer.analyze_convergence([50.0, 49.0, 48.0], stalled_prompt)
    assert stop
    print("  [PASS] Second consecutive stall correctly terminated the loop.")
    print()

    print("Stage 33 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
