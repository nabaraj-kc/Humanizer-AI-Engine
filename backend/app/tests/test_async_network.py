"""
backend/app/tests/test_async_network.py
=======================================
End-to-End Async Network Integration Test.
Validates file upload, background global context extraction, and WebSocket status broadcast.
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

import sys
import uuid
import logging
from pathlib import Path
from fastapi.testclient import TestClient

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[3]))

from backend.app.main import app
from backend.app.db.session import get_async_session
from backend.app.core.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_async_network")


def test_async_network_lifecycle():
    print("=== Stage 21: Async Network Integration Test ===")
    print()

    client = TestClient(app)
    client_id = str(uuid.uuid4())
    settings = get_settings()

    print("  --- Test 1: Connect WebSocket & Upload PDF File ---")
    
    # Establish WebSocket status link
    with client.websocket_connect(f"/ws/status/{client_id}") as ws:
        # Mini valid PDF stream bytes
        pdf_bytes = (
            b"%PDF-1.4\n"
            b"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
            b"2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj\n"
            b"3 0 obj <</Type /Page /Parent 2 0 R /MediaBox [0 0 595 842]>> endobj\n"
            b"xref\n"
            b"0 4\n"
            b"0000000000 65535 f\n"
            b"0000000009 00000 n\n"
            b"0000000056 00000 n\n"
            b"0000000111 00000 n\n"
            b"trailer <</Size 4 /Root 1 0 R>>\n"
            b"startxref\n"
            b"190\n"
            b"%%EOF"
        )
        
        # Trigger file upload endpoint
        files = {"file": ("test_integration.pdf", pdf_bytes, "application/pdf")}
        response = client.post("/api/upload", files=files)
        
        assert response.status_code == 200, f"Expected 200 upload status, got {response.status_code}"
        data = response.json()
        assert data["status"] == "success"
        run_id = data["run_id"]
        print(f"  [PASS] PDF successfully uploaded. Assigned run_id: {run_id}")

        # In TestClient, background tasks run synchronously.
        # This means the run_pipeline_in_background task has completed, and broadcasted to WS.
        # Check if WebSocket received progress event broadcast.
        states = []
        for _ in range(10):
            try:
                broadcast_msg = ws.receive_json()
                states.append(broadcast_msg.get("progress_state"))
                if broadcast_msg.get("progress_state") == "completed":
                    break
            except Exception:
                break
        assert "completed" in states, f"Expected 'completed' in progress states, got {states}"
        print(f"  [PASS] WebSocket successfully captured broadcast message: {broadcast_msg}")

    # Now verify the database record contains a valid, non-NULL master summary
    print()
    print("  --- Test 2: Global Context Extractor DB Check ---")
    
    async def verify_master_summary():
        async with get_async_session() as db:
            async with db.execute(
                "SELECT master_summary, status FROM paper_runs WHERE run_id = :run_id",
                {"run_id": run_id}
            ) as cur:
                row = await cur.fetchone()
                return row

    row = asyncio.run(verify_master_summary())
    assert row is not None
    assert row["master_summary"] is not None
    assert "THESIS:" in row["master_summary"]
    assert "METHODOLOGY:" in row["master_summary"]
    assert "GLOSSARY:" in row["master_summary"]
    print(f"  [PASS] Verified master_summary is saved in DB and is non-NULL.")
    print(f"         Summary preview:\n{row['master_summary'][:150]}...")
    print()

    # Clean up test artifact PDF file and DB record
    uploaded_file_path = settings.storage_dir / f"{run_id}.pdf"
    if uploaded_file_path.exists():
        uploaded_file_path.unlink()
        
    async def cleanup_db():
        async with get_async_session() as db:
            await db.execute("DELETE FROM paper_runs WHERE run_id = :run_id", {"run_id": run_id})

    asyncio.run(cleanup_db())
    print("  [PASS] Integration test resources cleaned up successfully.")
    print()
    print("Stage 21 integration check: ALL PASSED.")


if __name__ == "__main__":
    test_async_network_lifecycle()
