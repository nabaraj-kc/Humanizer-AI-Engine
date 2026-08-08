"""
frontend/serve_local.py
=======================
Static python server for local front-end environment testing.
Maps port 8080 to frontend assets directory, disables browser caching,
and cleans port binding conflicts on startup.
"""

import os
import sys
import socket
import subprocess
import http.server
import socketserver
from pathlib import Path

PORT = 8080
FRONTEND_DIR = Path(__file__).resolve().parent


class CacheDisabledHTTPHandler(http.server.SimpleHTTPRequestHandler):
    """
    Custom HTTP request handler that forces cache invalidation response headers
    and overrides the default file lookup path to target the frontend folder.
    """
    def __init__(self, *args, **kwargs):
        # Enforce serving files relative to the frontend directory
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def end_headers(self):
        # Send explicit anti-caching response headers
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


def kill_processes_on_port(port: int):
    """
    Locates and terminates any existing processes binding to the target port.
    Prevents SocketError: Address already in use errors on start.
    """
    current_pid = os.getpid()
    
    if sys.platform == "win32":
        try:
            # Query netstat for active port binds
            cmd = f"netstat -ano | findstr :{port}"
            output = subprocess.check_output(cmd, shell=True).decode("utf-8")
            pids = set()
            for line in output.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.strip().split()
                if len(parts) >= 5:
                    # netstat columns: Proto, Local Address, Foreign Address, State, PID
                    local_address = parts[1]
                    if f":{port}" in local_address:
                        pid_str = parts[-1]
                        if pid_str.isdigit():
                            pids.add(int(pid_str))
            
            for pid in pids:
                if pid != current_pid and pid > 0:
                    print(f"Cleaning socket conflict: Terminating PID {pid} bound to port {port}...")
                    subprocess.run(f"taskkill /F /PID {pid}", shell=True, check=True)
        except subprocess.CalledProcessError:
            # No process was listening on the port, which is a success condition
            pass
        except Exception as e:
            print(f"Warning: Failed to clean port conflicts: {e}")
    else:
        # Unix fallback (lsof / kill)
        try:
            cmd = f"lsof -t -i:{port}"
            output = subprocess.check_output(cmd, shell=True).decode("utf-8")
            pids = [int(p) for p in output.strip().split("\n") if p.strip().isdigit()]
            for pid in pids:
                if pid != current_pid:
                    print(f"Cleaning socket conflict: Terminating PID {pid} bound to port {port}...")
                    subprocess.run(f"kill -9 {pid}", shell=True, check=True)
        except subprocess.CalledProcessError:
            pass
        except Exception as e:
            print(f"Warning: Failed to clean port conflicts: {e}")


def is_port_in_use(port: int) -> bool:
    """Check if the port is currently occupied."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def run_server():
    print(f"=== Starting Static Local Web Server for Humanizer Frontend ===")
    print(f"Target Directory: {FRONTEND_DIR}")
    print(f"Target Port: {PORT}")

    # Enforce socket conflict cleanup guardrail
    if is_port_in_use(PORT):
        print(f"Port {PORT} is currently in use. Initializing cleanup conflict routine...")
        kill_processes_on_port(PORT)

    # Secondary bind verification
    if is_port_in_use(PORT):
        print(f"Error: Could not release port {PORT} for binding.")
        sys.exit(1)

    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("", PORT), CacheDisabledHTTPHandler) as httpd:
            print(f"Server successfully started at http://localhost:{PORT}")
            print("Press Ctrl+C to terminate the process.")
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer terminated by user. Exiting...")
    except Exception as e:
        print(f"\nServer runtime error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_server()
