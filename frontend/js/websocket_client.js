/**
 * frontend/js/websocket_client.js
 * ===============================
 * Frontend WebSocket Event Processing Controller.
 * Manages bi-directional pipeline statuses, socket connection bulbs, and backoff retries.
 */

class WebSocketClient {
    /**
     * @param {string} clientId Unique UUID identifier for the client session.
     * @param {string} host Optional websocket host override (e.g. localhost:8000).
     */
    constructor(clientId, host = null) {
        this.clientId = clientId;
        this.host = host || window.location.host || 'localhost:8000';
        
        // WS endpoint protocol mapping (secure vs standard)
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.url = `${protocol}//${this.host}/ws/status/${clientId}`;

        this.socket = null;
        this.onMessageCallback = null;
        this.onStatusChangeCallback = null;

        // Exponential backoff parameters
        this.reconnectDelay = 1000; // start with 1 second delay
        this.maxReconnectDelay = 16000; // cap at 16 seconds
        this.reconnectMultiplier = 2;
        this.reconnectTimer = null;
        this.isClosedIntentionally = false;
    }

    /**
     * Initialize connection to the ASGI WebSocket gateway.
     */
    connect() {
        this.isClosedIntentionally = false;
        console.log(`Connecting to WebSocket: ${this.url}`);
        
        if (this.onStatusChangeCallback) {
            this.onStatusChangeCallback('connecting');
        }

        try {
            this.socket = new WebSocket(this.url);
            
            this.socket.onopen = (event) => this._onOpen(event);
            this.socket.onmessage = (event) => this._onMessage(event);
            this.socket.onclose = (event) => this._onClose(event);
            this.socket.onerror = (event) => this._onError(event);
        } catch (err) {
            console.error('Failed to instantiate WebSocket connection:', err);
            this._scheduleReconnect();
        }
    }

    /**
     * Terminate the socket connection intentionally.
     */
    disconnect() {
        this.isClosedIntentionally = true;
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        if (this.socket) {
            this.socket.close();
            this.socket = null;
        }
    }

    _onOpen(event) {
        console.log('WebSocket connection established.');
        this.reconnectDelay = 1000; // Reset backoff delay on successful connection
        if (this.onStatusChangeCallback) {
            this.onStatusChangeCallback('connected');
        }
    }

    _onMessage(event) {
        try {
            const data = JSON.parse(event.data);
            if (this.onMessageCallback) {
                this.onMessageCallback(data);
            }
        } catch (err) {
            console.error('Failed to parse WebSocket JSON payload:', err);
        }
    }

    _onClose(event) {
        console.log(`WebSocket connection closed. status=${event.code}`);
        if (this.onStatusChangeCallback) {
            this.onStatusChangeCallback('disconnected');
        }

        if (!this.isClosedIntentionally) {
            this._scheduleReconnect();
        }
    }

    _onError(event) {
        console.error('WebSocket connection error occurred:', event);
        // OnError triggers onClose, so we let onClose handle the reconnect logic
    }

    _scheduleReconnect() {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
        }

        console.log(`Scheduling auto-reconnect in ${this.reconnectDelay}ms...`);
        this.reconnectTimer = setTimeout(() => {
            this.connect();
            // Double the delay for the next attempt, capped at max
            this.reconnectDelay = Math.min(
                this.maxReconnectDelay,
                this.reconnectDelay * this.reconnectMultiplier
            );
        }, this.reconnectDelay);
    }
}

// ---------------------------------------------------------------------------
// Inline Client-Side Testing Suite
// ---------------------------------------------------------------------------
function test_websocket_client() {
    console.log("=== Running WebSocketClient Unit Test Checks ===");

    let statusTransitionLogs = [];
    const client = new WebSocketClient("test-uuid-client", "localhost:9999"); // Fake port to force connection failures
    
    client.onStatusChangeCallback = (status) => {
        statusTransitionLogs.push(status);
        console.log(`  [TEST STATUS CHANGE]: ${status}`);
    };

    // Test 1: Connect triggers 'connecting' status
    client.connect();
    if (statusTransitionLogs[0] === 'connecting') {
        console.log("  [PASS] Connect triggers initial connecting state.");
    } else {
        console.error("  [FAIL] Connecting state not triggered.");
    }

    // Test 2: Exponential backoff calculation check
    setTimeout(() => {
        // Assert reconnectDelay has doubled
        const currentDelay = client.reconnectDelay;
        if (currentDelay > 1000) {
            console.log(`  [PASS] Backoff multiplied successfully. Next delay: ${currentDelay}ms.`);
        } else {
            console.error("  [FAIL] Reconnect delay did not multiply.");
        }
        client.disconnect();
        console.log("=== WebSocketClient tests completed ===");
    }, 1500);
}

// Expose to window/global scope or run if specifically invoked
if (typeof window !== 'undefined') {
    window.WebSocketClient = WebSocketClient;
    window.test_websocket_client = test_websocket_client;
}
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { WebSocketClient };
}
