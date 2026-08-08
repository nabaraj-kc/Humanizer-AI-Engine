"""
backend/app/tests/test_frontend_tier.py
=======================================
Frontend Tier Integration Test Suite.
Launches the static HTTP python server in a background process, queries
endpoints via urllib, and asserts DOM/script structures and Cache-Control headers.
"""

import os
import sys
import time
import urllib.request
import subprocess
from pathlib import Path

# Resolve project root path
project_root = Path(__file__).resolve().parents[3]
sys.path.append(str(project_root))

from backend.app.core.config import get_settings


def test_frontend_server_lifecycle():
    print("=== Stage 48: Front-End Core Tier Integration Test ===")
    print()

    server_script = project_root / "frontend" / "serve_local.py"
    if not server_script.exists():
        print(f"  [FAIL] serve_local.py not found at: {server_script}")
        sys.exit(1)

    print("  --- Test 1: Spawning serve_local.py on background process ---")
    
    # Spawn background server process
    proc = subprocess.Popen(
        [sys.executable, str(server_script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    time.sleep(2.0) # Wait for server port binding and conflict checks to execute
    
    # Guard to check if process crashed on startup
    if proc.poll() is not None:
        stdout, stderr = proc.communicate()
        print(f"  [FAIL] Server failed to start. stdout:\n{stdout}\nstderr:\n{stderr}")
        sys.exit(1)

    print("  [PASS] Static Python HTTP server process spawned.")

    url_base = "http://localhost:8080"
    
    try:
        # Test 2: Verify root endpoint index.html retrieval and cache-control headers
        print()
        print("  --- Test 2: Retrieving root index.html asset and verifying cache-control headers ---")
        
        req = urllib.request.Request(url_base)
        with urllib.request.urlopen(req, timeout=5) as response:
            assert response.status == 200, f"Expected status 200, got {response.status}"
            
            # Verify headers
            headers = response.info()
            cache_control = headers.get("Cache-Control", "")
            print(f"  Cache-Control header received: '{cache_control}'")
            assert "no-store" in cache_control.lower(), "Expected 'no-store' in Cache-Control response headers"
            assert "no-cache" in cache_control.lower(), "Expected 'no-cache' in Cache-Control response headers"
            print("  [PASS] Anti-cache response headers verified successfully.")

            # Verify HTML contents
            html_content = response.read().decode("utf-8")
            
            # Check critical DOM anchors
            required_selectors = [
                'id="ws-status-bulb"',
                'id="ws-status-text"',
                'id="quota-bar-google"',
                'id="quota-bar-groq"',
                'id="quota-bar-deepseek"',
                'id="alert-warning-box"',
                'id="pdf-upload-zone"',
                'id="pdf-file-input"',
                'id="svg-visualization-container"',
                'id="processing-stats-text"'
            ]
            
            for selector in required_selectors:
                assert selector in html_content, f"Required DOM selector missing in index.html: {selector}"
            print("  [PASS] All critical DOM component selectors identified.")

            # Check script links
            required_scripts = [
                'src="js/websocket_client.js"',
                'src="js/pipeline_view.js"',
                'src="js/app.js"',
                'href="css/style.css"'
            ]
            for script in required_scripts:
                assert script in html_content, f"Required asset link missing in index.html: {script}"
            print("  [PASS] All core JS/CSS script bundle links identified.")

        # Test 3: Download individual assets
        print()
        print("  --- Test 3: Asserting asset bundle downloads ---")
        
        assets = [
            "/css/style.css",
            "/js/websocket_client.js",
            "/js/pipeline_view.js",
            "/js/app.js"
        ]
        
        for asset in assets:
            asset_url = f"{url_base}{asset}"
            with urllib.request.urlopen(asset_url, timeout=5) as res:
                assert res.status == 200, f"Failed to download asset {asset}. Status: {res.status}"
                content_len = len(res.read())
                print(f"  [PASS] Downloaded {asset} ({content_len} bytes) - Status 200")

    finally:
        # Enforce server cleanup termination
        print()
        print("  --- Test 4: Terminating background server process ---")
        proc.terminate()
        try:
            proc.wait(timeout=3)
            print("  [PASS] Server process terminated normally.")
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            print("  [PASS] Server process killed forcefully.")

    print()
    print("Stage 48 integration check: ALL PASSED.")


if __name__ == "__main__":
    test_frontend_server_lifecycle()
