"""
backend/app/services/alignment_engine.py
=========================================
Layout Coordinate Matching Logic.
Aligns rewritten text chunks back to original document coordinate structures.
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

from backend.app.services.layout_mapper import DocumentStructureMap

logger = logging.getLogger("humanizer_alignment_engine")


class AlignmentError(Exception):
    """Raised when paragraph matching sequences fail validation checks."""
    pass


class LayoutAlignmentEngine:
    """
    Data engine class that aligns processed text chunks back with
    their original PDF layout containers using sequence numbers.
    """

    def __init__(self, original_blocks: list[dict], chunks_meta: list[dict]):
        self.structure_map = DocumentStructureMap(original_blocks)
        self.structure_map.register_chunks(chunks_meta)

    def align_processed_chunks(self, processed_chunks: list[dict]) -> list[dict]:
        """
        Maps processed text blocks back into original bounding containers.
        Accepts:
          processed_chunks: list of dicts with keys 'sequence_no' and 'processed'
        Returns:
          list of dicts containing page_no, block_no, x0, y0, x1, y1, original_text, rewritten_text
        """
        seq_nos = [c.get("sequence_no") for c in processed_chunks]
        
        # Enforce compulsory verification guardrail: check for duplicate indices
        if len(seq_nos) != len(set(seq_nos)):
            logger.error("Duplicate sequence numbers found in processed chunks.")
            raise AlignmentError("Duplicate sequence numbers found in processed chunks.")

        # Enforce compulsory verification guardrail: check for missing indices
        total_expected = len(self.structure_map.registered_chunks)
        expected_seqs = set(range(total_expected))
        actual_seqs = set(seq_nos)
        
        missing_seqs = expected_seqs - actual_seqs
        if missing_seqs:
            logger.error(f"Missing sequence indices in processed chunks: {missing_seqs}")
            raise AlignmentError(f"Missing sequence numbers in processed chunks: {missing_seqs}")

        extra_seqs = actual_seqs - expected_seqs
        if extra_seqs:
            logger.error(f"Unexpected extra sequence indices in processed chunks: {extra_seqs}")
            raise AlignmentError(f"Extra sequence numbers in processed chunks: {extra_seqs}")

        # Construct rewrite mapping dictionary for DocumentStructureMap
        rewritten_dict = {c["sequence_no"]: c["processed"] for c in processed_chunks}

        try:
            mapped_blocks = self.structure_map.map_rewritten_chunks(rewritten_dict)
            return [dict(b) for b in mapped_blocks]
        except Exception as e:
            logger.error(f"Failed during layout mapping distribution: {e}")
            raise AlignmentError(f"Layout mapping distribution failure: {e}") from e


# ---------------------------------------------------------------------------
# Stage 36 Verification Guardrail Tests
# ---------------------------------------------------------------------------
def run_tests() -> None:
    print("=== Stage 36: Layout Alignment Engine Verification ===")
    print()

    # Create dummy original blocks and chunks metadata
    dummy_blocks = [
        {"page_no": 0, "block_no": 10, "x0": 10.0, "y0": 20.0, "x1": 100.0, "y1": 50.0, "text": "Sentence 1 text."},
        {"page_no": 0, "block_no": 11, "x0": 10.0, "y0": 60.0, "x1": 100.0, "y1": 90.0, "text": "Sentence 2 text."}
    ]

    dummy_chunks_meta = [
        {"chunk_id": 0, "paragraph_indices": [10], "text": "Sentence 1 text."},
        {"chunk_id": 1, "paragraph_indices": [11], "text": "Sentence 2 text."}
    ]

    engine = LayoutAlignmentEngine(dummy_blocks, dummy_chunks_meta)

    # 1. Successful alignment
    print("  --- Test 1: Successful mapping alignment ---")
    processed_ok = [
        {"sequence_no": 0, "processed": "Rewritten Sentence 1 text."},
        {"sequence_no": 1, "processed": "Rewritten Sentence 2 text."}
    ]
    aligned = engine.align_processed_chunks(processed_ok)
    assert len(aligned) == 2
    assert aligned[0]["rewritten_text"] == "Rewritten Sentence 1 text."
    assert aligned[0]["x0"] == 10.0
    print("  [PASS] Mapping aligned correctly with coordinates.")
    print()

    # 2. Duplicate sequence validation error
    print("  --- Test 2: Duplicate sequence index guardrail check ---")
    processed_dup = [
        {"sequence_no": 0, "processed": "Rewritten 1."},
        {"sequence_no": 0, "processed": "Duplicate 1."}
    ]
    try:
        engine.align_processed_chunks(processed_dup)
        assert False, "Expected AlignmentError for duplicate sequence"
    except AlignmentError as e:
        print(f"  [PASS] Correctly rejected duplicate indices: {e}")
    print()

    # 3. Missing sequence validation error
    print("  --- Test 3: Missing sequence index guardrail check ---")
    processed_missing = [
        {"sequence_no": 1, "processed": "Only chunk 1."}
    ]
    try:
        engine.align_processed_chunks(processed_missing)
        assert False, "Expected AlignmentError for missing sequence"
    except AlignmentError as e:
        print(f"  [PASS] Correctly rejected missing indices: {e}")
    print()

    print("Stage 36 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
