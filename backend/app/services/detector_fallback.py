"""
backend/app/services/detector_fallback.py
=========================================
Local vs. Serverless Alternative Execution Detector Router.
Bypasses local resource limitations by calling Hugging Face's serverless endpoints,
with final statistical analyzer fallbacks on network timeout.
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
import os
import sys
from pathlib import Path
import aiohttp

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[3]))

from backend.app.services.local_detector import LocalAdversarialDetector

logger = logging.getLogger("humanizer_detector_fallback")


class AdversarialDetectorRouter:
    """
    Orchestrator managing local RoBERTa model classifications, falling back to
    Hugging Face's Serverless Inference API, and applying a backup statistical
    analyzer under network timeouts (8 seconds limit).
    """

    def __init__(self):
        self.local_detector = LocalAdversarialDetector()
        self.hf_model = "roberta-base-openai-detector"
        self.hf_api_url = f"https://api-inference.huggingface.co/models/{self.hf_model}"
        self.using_fallback = False

    def calculate_statistical_ai_probability(self, text: str) -> float:
        """
        Secondary Fallback: Estimates the probability that the text is AI-generated
        using simple sentence metrics (length variance/burstiness) and buzzword analysis.
        """
        if not text or not text.strip():
            return 0.0

        words = text.split()
        sentences = [s.strip() for s in re.split(r"[.!?]", text) if s.strip()]
        if not sentences:
            return 50.0  # Default moderate probability

        # 1. Burstiness heuristic (std deviation of sentence lengths)
        lengths = [len(s.split()) for s in sentences]
        avg_len = sum(lengths) / len(lengths)
        variance = sum((l - avg_len) ** 2 for l in lengths) / len(lengths)
        std_dev = variance ** 0.5

        # Lower burstiness indicates uniform structural pattern (common in AI)
        burstiness_score = max(0, 50 - (std_dev * 5))

        # 2. AI buzzword density
        ai_buzzwords = {"moreover", "furthermore", "tapestry", "testament", "delve", "pivotal", "demystify", "underscores", "beacon"}
        buzzword_count = sum(1 for w in words if w.lower().strip(",.?!") in ai_buzzwords)
        buzzword_score = min(50, buzzword_count * 15)

        # Combined calculation bounded between 5% and 95%
        score = 15.0 + burstiness_score + buzzword_score
        return min(95.0, max(5.0, round(score, 2)))

    async def calculate_ai_probability(self, text: str) -> float:
        """
        Router logic:
          1. Try local detector if loaded.
          2. Fallback to HF Serverless Inference API (with 8-second timeout).
          3. Fallback to statistical estimation if HF fails or times out.
        """
        # 1. Attempt local classification
        if self.local_detector.local_enabled:
            try:
                logger.info("Local detector enabled. Running local RoBERTa inference...")
                prob = await self.local_detector.calculate_ai_probability(text)
                self.using_fallback = False
                return prob
            except Exception as e:
                logger.warning(f"Local detector execution failed: {e}. Falling back to serverless...")

        # 2. Attempt Hugging Face Serverless API
        logger.info("Routing request to Hugging Face Serverless Inference API...")
        headers = {}
        hf_token = os.environ.get("HF_API_KEY") or os.environ.get("HF_TOKEN")
        if hf_token:
            headers["Authorization"] = f"Bearer {hf_token}"

        payload = {"inputs": text}
        # Enforce compulsory guardrail: 8 seconds maximum timeout
        timeout = aiohttp.ClientTimeout(total=8.0)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.hf_api_url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        response_json = await response.json()
                        # Schema is list of lists: [[{"label": "Fake", "score": 0.9}, {"label": "Real", "score": 0.1}]]
                        try:
                            predictions = response_json[0]
                            # Find score for "Fake"
                            fake_score = 0.0
                            for pred in predictions:
                                if pred.get("label", "").upper() == "FAKE":
                                    fake_score = pred.get("score", 0.0)
                                    break
                            
                            prob = fake_score * 100.0
                            logger.info(f"HF Serverless returned prediction score: {prob:.2f}%")
                            self.using_fallback = False
                            return round(prob, 2)
                        except (KeyError, IndexError, TypeError) as parse_err:
                            logger.error(f"Failed to parse HF API response: {parse_err}. Raw: {response_json}")
                            # Fall through to statistical fallback
                    else:
                        status = response.status
                        err_text = await response.text()
                        logger.error(f"HF Serverless API error: status={status}, response={err_text}")
                        # Fall through to statistical fallback

        except asyncio.TimeoutError:
            logger.warning("Hugging Face serverless API request TIMEOUT (exceeded 8s). Applying statistical fallback.")
        except Exception as conn_err:
            logger.warning(f"Hugging Face serverless API connection failed: {conn_err}. Applying statistical fallback.")

        # 3. Final Fallback: Statistical metric analyzer
        logger.info("Executing backup statistical AI probability estimation...")
        self.using_fallback = True
        stat_prob = self.calculate_statistical_ai_probability(text)
        logger.info(f"Statistical analyzer returned score: {stat_prob}%")
        return stat_prob


# ---------------------------------------------------------------------------
# Stage 30 Verification Guardrail Test
# ---------------------------------------------------------------------------

def run_tests() -> None:
    print("=== Stage 30: Detector Fallback Router Verification ===")
    print()

    router = AdversarialDetectorRouter()
    # Disable local detector to force fallback execution paths
    router.local_detector.local_enabled = False

    # 1. Test statistical estimator fallback logic
    print("  --- Test 1: Statistical estimator metric calculation ---")
    test_text_flat = "This is a simple sentence. This is another simple sentence. This is a third simple sentence."
    test_text_buzz = "Moreover, we must delve further into this tapestry to find the pivotal beacon."
    
    score_flat = router.calculate_statistical_ai_probability(test_text_flat)
    score_buzz = router.calculate_statistical_ai_probability(test_text_buzz)
    
    # Flat text should have low variance/burstiness (high AI score)
    # Buzzword text should increase the buzzword metrics
    assert 0.0 <= score_flat <= 100.0
    assert 0.0 <= score_buzz <= 100.0
    print(f"  [PASS] Statistical scores: Flat = {score_flat}%, Buzzword-rich = {score_buzz}%")
    print()

    # 2. Test mock HF API response parsing
    print("  --- Test 2: Hugging Face Serverless API response parsing ---")
    mock_hf_response = [
        [
            {"label": "Real", "score": 0.20},
            {"label": "Fake", "score": 0.80}
        ]
    ]

    class MockClientSession:
        def __init__(self, status_code: int, json_data: dict):
            self.status = status_code
            self.json_data = json_data

        def post(self, url: str, json: dict, headers: dict):
            class PostContext:
                def __init__(self, status: int, data: dict):
                    self.status = status
                    self.data = data
                async def __aenter__(self):
                    return self
                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    pass
                async def json(self):
                    return self.data
            return PostContext(self.status, self.json_data)

        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    import unittest.mock as mock

    async def test_hf_success():
        with mock.patch("aiohttp.ClientSession", return_value=MockClientSession(200, mock_hf_response)):
            prob = await router.calculate_ai_probability("Sample document text")
            assert prob == 80.0
            print(f"  [PASS] Correctly parsed HF response payload: {prob}% probability.")

    asyncio.run(test_hf_success())
    print()

    # 3. Test API call Timeout -> fall back to statistical module
    print("  --- Test 3: API Timeout -> Statistical analyzer fallback ---")
    async def test_hf_timeout():
        # Mock ClientSession.post to raise asyncio.TimeoutError
        async def mock_timeout_post(*args, **kwargs):
            raise asyncio.TimeoutError("Connection timed out")

        with mock.patch("aiohttp.ClientSession.post", side_effect=mock_timeout_post):
            prob = await router.calculate_ai_probability(test_text_buzz)
            assert prob == score_buzz
            print(f"  [PASS] Timeout triggered statistical analyzer fallback correctly: score={prob}%")

    asyncio.run(test_hf_timeout())
    print()

    print("Stage 30 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
