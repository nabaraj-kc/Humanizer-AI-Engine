"""
backend/app/core/websocket_manager.py
=====================================
Live status event broadcasting dispatcher.
Manages websocket connections and broadcasts pipeline updates safely.
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

import logging
from datetime import datetime
from fastapi import WebSocket
from pydantic import BaseModel, Field

logger = logging.getLogger("humanizer_ws_manager")


# ---------------------------------------------------------------------------
# Strict Message Schema Mappings
# ---------------------------------------------------------------------------

class TokenUpdates(BaseModel):
    google: int = 0
    groq: int = 0
    deepseek: int = 0


class PipelineStatusMessage(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    category: str  # e.g., "info", "progress", "token_update", "error"
    progress_state: str  # e.g., "idle", "parsing", "rewriting", "completed", "failed"
    token_updates: TokenUpdates


# ---------------------------------------------------------------------------
# WebSocket Manager Controller
# ---------------------------------------------------------------------------

class WebSocketManager:
    """
    Manages active WebSocket connections for status broadcasting.
    Handles personal messaging, multi-socket broadcasting, and stale link pruning.
    """

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        """Upgrade and accept incoming WebSocket connection."""
        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info(f"WebSocket client_id={client_id} connected. Active links: {len(self.active_connections)}")

    def disconnect(self, client_id: str) -> None:
        """Remove WebSocket connection references."""
        self.active_connections.pop(client_id, None)
        logger.info(f"WebSocket client_id={client_id} disconnected. Active links: {len(self.active_connections)}")

    async def send_personal_message(self, message: dict | PipelineStatusMessage, client_id: str) -> None:
        """
        Sends a message to a specific connection.
        Enforces validation schema and cleans up on connection failures.
        """
        if isinstance(message, dict):
            validated = PipelineStatusMessage(**message)
        else:
            validated = message

        payload = validated.model_dump_json() if hasattr(validated, "model_dump_json") else validated.json()
        ws = self.active_connections.get(client_id)
        if ws:
            try:
                await ws.send_text(payload)
            except Exception as e:
                logger.warning(f"Error sending personal message to client_id={client_id}: {e}. Disconnecting...")
                self.disconnect(client_id)

    async def broadcast_global_message(self, message: dict | PipelineStatusMessage) -> None:
        """
        Broadcasts status updates to all active WebSocket connections.
        Automatically catches exceptions for stalled/dead links and prunes them.
        """
        if isinstance(message, dict):
            validated = PipelineStatusMessage(**message)
        else:
            validated = message

        payload = validated.model_dump_json() if hasattr(validated, "model_dump_json") else validated.json()
        dead_clients: list[str] = []

        # Broadcast to all clients. Exception safety prevents one bad socket from blocking others.
        for client_id, ws in list(self.active_connections.items()):
            try:
                await ws.send_text(payload)
            except Exception as e:
                logger.warning(f"Broadcast failed to client_id={client_id}: {e}. Tagging for removal.")
                dead_clients.append(client_id)

        # Remove dead clients cleanly
        for client_id in dead_clients:
            self.disconnect(client_id)


# Global Singleton Instance for shared routing import
ws_manager = WebSocketManager()


# ---------------------------------------------------------------------------
# Stage 18 Verification Guardrail Test
# ---------------------------------------------------------------------------

def run_tests() -> None:
    from fastapi import FastAPI, WebSocketDisconnect
    from fastapi.testclient import TestClient
    import uuid

    print("=== Stage 18: Live Event Broadcasting Manager Verification ===")
    print()

    app = FastAPI()
    test_manager = WebSocketManager()

    @app.websocket("/ws/{client_id}")
    async def test_ws_endpoint(websocket: WebSocket, client_id: str):
        await test_manager.connect(websocket, client_id)
        try:
            while True:
                # Keep loop alive to receive messages
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            test_manager.disconnect(client_id)

    client = TestClient(app)
    c1_id = str(uuid.uuid4())
    c2_id = str(uuid.uuid4())

    print("  --- Test 1: Parallel connections and standard broadcasting ---")
    
    with client.websocket_connect(f"/ws/{c1_id}") as ws1, \
         client.websocket_connect(f"/ws/{c2_id}") as ws2:
         
        assert c1_id in test_manager.active_connections
        assert c2_id in test_manager.active_connections
        print("  [PASS] Both connections active and tracked.")

        # Construct status update message
        status_msg = {
            "category": "progress",
            "progress_state": "rewriting",
            "token_updates": {"google": 240, "groq": 0, "deepseek": 0}
        }
        
        # Broadcast globally
        asyncio.run(test_manager.broadcast_global_message(status_msg))
        
        # Verify both received the serialized payload
        res1 = ws1.receive_json()
        res2 = ws2.receive_json()
        
        assert res1["category"] == "progress"
        assert res1["progress_state"] == "rewriting"
        assert res1["token_updates"]["google"] == 240
        assert res2["category"] == "progress"
        
        print("  [PASS] Global broadcast successfully delivered and parsed by all clients.")

    print()
    print("  --- Test 2: Dead connection pruning guardrail ---")

    # Connect client 1 and client 2 again
    with client.websocket_connect(f"/ws/{c1_id}") as ws1:
        # Mocking a closed connection state manually for client 2 by inserting a fake socket
        # that will throw an exception when send_text is called.
        class BrokenWebSocket:
            async def send_text(self, data: str):
                raise RuntimeError("Socket write error (simulated link drop)")
                
        test_manager.active_connections[c2_id] = BrokenWebSocket() # type: ignore
        
        assert c1_id in test_manager.active_connections
        assert c2_id in test_manager.active_connections

        # Attempt broadcast
        asyncio.run(test_manager.broadcast_global_message({
            "category": "info",
            "progress_state": "completed",
            "token_updates": {"google": 0, "groq": 0, "deepseek": 0}
        }))
        
        # Client 1 should have received the message successfully
        res1 = ws1.receive_json()
        assert res1["progress_state"] == "completed"
        print("  [PASS] Broadcast delivered to healthy connection despite broken peer.")
        
        # Client 2 should be automatically removed from active connections due to write failure
        assert c2_id not in test_manager.active_connections
        print("  [PASS] Stalled/dead connections pruned from manager dictionary automatically.")

    print()
    print("Stage 18 verification: ALL CHECKS PASSED.")


if __name__ == "__main__":
    run_tests()
