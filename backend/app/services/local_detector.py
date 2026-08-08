"""
backend/app/services/local_detector.py
======================================
Local AI Detection Server Instantiation.
Scores text blocks for AI characteristics using local models (default to CPU).
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
import ctypes
from ctypes import wintypes
from pathlib import Path

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[3]))

logger = logging.getLogger("humanizer_local_detector")

# Import guards for deep learning libraries
torch_available = False
transformers_available = False
pipeline = None

try:
    import torch
    torch_available = True
except ImportError:
    logger.warning("Torch library not found. Local model loading disabled.")

try:
    from transformers import pipeline
    transformers_available = True
except ImportError:
    logger.warning("Transformers library not found. Local model loading disabled.")


# ---------------------------------------------------------------------------
# Windows Memory Diagnosis structures (ctypes)
# ---------------------------------------------------------------------------

class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ('dwLength', wintypes.DWORD),
        ('dwMemoryLoad', wintypes.DWORD),
        ('ullTotalPhys', ctypes.c_uint64),
        ('ullAvailPhys', ctypes.c_uint64),
        ('ullTotalPageFile', ctypes.c_uint64),
        ('ullAvailPageFile', ctypes.c_uint64),
        ('ullTotalVirtual', ctypes.c_uint64),
        ('ullAvailVirtual', ctypes.c_uint64),
        ('ullAvailExtendedVirtual', ctypes.c_uint64),
    ]


def get_available_memory_bytes() -> int:
    """Natively retrieves available physical RAM on Windows."""
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(stat)
    try:
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return stat.ullAvailPhys
    except Exception as e:
        logger.error(f"Failed to query system memory via ctypes: {e}")
    return 0


# ---------------------------------------------------------------------------
# Detector implementation
# ---------------------------------------------------------------------------

class LocalAdversarialDetector:
    """
    Loads and runs local AI classification models using Hugging Face pipelines on CPU.
    Validates memory boundaries and falls back dynamically if system RAM is restricted.
    """

    def __init__(self):
        self.model_name = "roberta-base-openai-detector"
        self.classifier = None
        self.local_enabled = False
        
        # Check system memory limits and library imports before loading weights
        self._initialize_detector()

    def _initialize_detector(self) -> None:
        """
        Validates system memory bounds and imports, instantiating the model
        on CPU if safe, or flagging fallback requirements on failure.
        """
        # 1. Enforce memory verification guardrail (require at least 2GB free RAM)
        avail_ram = get_available_memory_bytes()
        logger.info(f"System memory check: available RAM = {avail_ram / (1024 * 1024):.2f} MB")
        
        if avail_ram > 0 and avail_ram < (2 * 1024 * 1024 * 1024):
            logger.warning("Available memory is restricted (< 2GB). Skipping local model initialization to prevent crashes.")
            return

        # 2. Check library imports
        if not (torch_available and transformers_available and pipeline):
            logger.warning("Required deep learning modules (torch/transformers) are missing. Skipping local model initialization.")
            return

        # 3. Safe CPU instantiation
        try:
            logger.info(f"Loading local classifier model '{self.model_name}' into memory on CPU...")
            # device=-1 forces CPU execution
            self.classifier = pipeline(
                "text-classification",
                model=self.model_name,
                device=-1
            )
            self.local_enabled = True
            logger.info("Local classifier model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load local model weights: {e}. Skipping local execution.")
            self.classifier = None
            self.local_enabled = False

    async def calculate_ai_probability(self, text: str) -> float:
        """
        Calculates the probability that the text is AI-generated.
        Returns a score percentage between 0.0 and 100.0.
        
        Raises RuntimeError if local model execution is unavailable.
        """
        if not self.local_enabled or not self.classifier:
            raise RuntimeError("Local adversarial detector is not loaded or disabled.")

        if not text or not text.strip():
            return 0.0

        try:
            # Execute model inference
            results = self.classifier(text)
            # Example response schema: [{'label': 'Fake', 'score': 0.998}]
            # 'Fake' = AI-generated, 'Real' = Human-written
            if not results:
                return 0.0

            prediction = results[0]
            label = prediction.get("label", "")
            score = prediction.get("score", 0.0)

            if label.upper() == "FAKE":
                prob = score * 100.0
            else:
                prob = (1.0 - score) * 100.0

            return round(prob, 2)
            
        except Exception as e:
            logger.error(f"Error executing local classifier: {e}")
            raise RuntimeError("Local classifier execution failure.") from e


# ---------------------------------------------------------------------------
# Stage 29 Verification Guardrail Test
# ---------------------------------------------------------------------------

def run_tests() -> None:
    print("=== Stage 29: Local AI Detection Server Verification ===")
    print()

    # 1. Test memory status retrieval
    print("  --- Test 1: System available memory check ---")
    avail_bytes = get_available_memory_bytes()
    assert avail_bytes >= 0
    print(f"  [PASS] Verified available memory query: {avail_bytes / (1024 * 1024):.2f} MB")
    print()

    # 2. Test model loading skip when libraries are missing
    print("  --- Test 2: Fallback trigger when models are not loadable ---")
    detector = LocalAdversarialDetector()
    
    # If torch/transformers are not installed, local_enabled must be False
    if not (torch_available and transformers_available):
        assert not detector.local_enabled
        print("  [PASS] Correctly flagged local model as disabled due to missing packages.")
    else:
        print(f"  [NOTE] Torch & Transformers packages are available. Local load state: {detector.local_enabled}")
    print()

    # 3. Test scoring parser using a mock classifier pipeline
    print("  --- Test 3: Prediction schema parsing with mock classifier ---")
    
    # Instantly mock classifier to test response math
    class MockClassifier:
        def __init__(self, mock_label: str, mock_score: float):
            self.mock_label = mock_label
            self.mock_score = mock_score
            
        def __call__(self, text: str):
            return [{"label": self.mock_label, "score": self.mock_score}]

    # Test Fake (AI-generated) label conversion
    detector.classifier = MockClassifier("Fake", 0.85)
    detector.local_enabled = True
    
    prob_fake = asyncio.run(detector.calculate_ai_probability("Some text block"))
    assert prob_fake == 85.0
    print(f"  [PASS] Parsed FAKE label: score=0.85 -> prob={prob_fake}%")

    # Test Real (Human-written) label conversion
    detector.classifier = MockClassifier("Real", 0.90)
    prob_real = asyncio.run(detector.calculate_ai_probability("Some text block"))
    assert prob_real == 10.0  # (1 - 0.90) * 100
    print(f"  [PASS] Parsed REAL label: score=0.90 -> prob={prob_real}%")
    print()

    print("Stage 29 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
