"""
backend/app/api/websockets.py
=============================
Asynchronous WebSocket Gateway Endpoint.
Handles protocol upgrades, socket registration, and client-disconnect cleanup.
"""

import logging
import sys
from pathlib import Path
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
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parents[3]))

logger = logging.getLogger("humanizer_ws")

router = APIRouter()

# Active connections map (client_id -> WebSocket)
active_connections: dict[str, WebSocket] = {}


@router.websocket("/ws/status/{client_id}")
async def websocket_status_endpoint(websocket: WebSocket, client_id: str):
    """
    WebSocket endpoint handling client registration and status communication loops.
    """
    from backend.app.core.websocket_manager import ws_manager
    # ws_manager.connect accepts the websocket internally
    await ws_manager.connect(websocket, client_id)
    active_connections[client_id] = websocket
    logger.info(f"WebSocket registered for client_id={client_id}. Active connections count: {len(active_connections)}")

    try:
        while True:
            # Standard message listen loop (usually ping/pong or basic client telemetry requests)
            data = await websocket.receive_text()
            # Simple echoing protocol for validation
            await websocket.send_text(f"echo: {data}")
    except WebSocketDisconnect:
        logger.info(f"WebSocket client_id={client_id} disconnected normally (WebSocketDisconnect)")
    except Exception as e:
        logger.error(f"WebSocket error on connection client_id={client_id}: {e}")
    finally:
        # Enforce cleanup of references
        from backend.app.core.websocket_manager import ws_manager
        ws_manager.disconnect(client_id)
        active_connections.pop(client_id, None)
        logger.info(f"Connection for client_id={client_id} removed. Active connections count: {len(active_connections)}")


# ---------------------------------------------------------------------------
# Stage 17 Verification Guardrail Test
# ---------------------------------------------------------------------------

def run_tests() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import uuid

    print("=== Stage 17: Asynchronous WebSocket Gateway Verification ===")
    print()

    # Create a local test FastAPI app to test the WebSocket router isolation
    test_app = FastAPI()
    test_app.include_router(router)

    client = TestClient(test_app)
    client_id = str(uuid.uuid4())

    print("  --- Test 1: Connect and exchange messages (Echo verification) ---")
    with client.websocket_connect(f"/ws/status/{client_id}") as websocket:
        # Check that connection was saved
        assert client_id in active_connections, f"Expected client_id {client_id} to be registered in active connections"
        print(f"  [PASS] WebSocket successfully connected and registered. Active: {list(active_connections.keys())}")
        
        # Test sending message
        websocket.send_text("ping")
        response = websocket.receive_text()
        assert response == "echo: ping", f"Expected 'echo: ping', got '{response}'"
        print("  [PASS] Echo protocol message exchange verified.")

    print()
    print("  --- Test 2: Simulating unexpected link drop ---")
    # Verify that closing the context block registers as disconnect and removes client from active connections
    assert client_id not in active_connections, f"Expected client_id {client_id} to be removed from active connections after disconnect"
    print("  [PASS] Verified connection was cleaned up successfully after termination.")
    print()
    
    print("Stage 17 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
