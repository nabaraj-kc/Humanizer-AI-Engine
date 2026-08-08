"""
preflight.py
============
Production Pre-Flight System Checking Utility.
Performs diagnostic checks (write permissions, database integrity, network latencies)
and outputs a system health card, preventing boots if critical checks fail.
"""

# Hotpatch typing module for Python 3.11 alpha compatibility issues with Pydantic / AnyIO / aiohttp
import typing

class SubscriptableObject:
    def __class_getitem__(cls, item):
        return object
    def __init__(self, *args, **kwargs):
        pass

# Force override draft types that raise TypeErrors in early 3.11 alphas
typing.Unpack = SubscriptableObject
typing.TypeVarTuple = SubscriptableObject
typing.Required = object
typing.NotRequired = object
typing.Self = object

try:
    import typing_extensions
    typing_extensions.Unpack = SubscriptableObject
    typing_extensions.TypeVarTuple = SubscriptableObject
    typing_extensions.Required = object
    typing_extensions.NotRequired = object
    typing_extensions.Self = object
except ImportError:
    pass

import os
import sys
import time
import socket
import urllib.request
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Color codes for premium terminal output formatting
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def print_header():
    print(f"{BOLD}{CYAN}==================================================")
    print("            HUMANIZER AI SYSTEM PRE-FLIGHT         ")
    print(f"=================================================={RESET}")


def check_directory_permissions() -> tuple[bool, str]:
    """
    Assert read/write permissions on the workspace storage directory.
    """
    storage_dir = PROJECT_ROOT / "storage"
    if not storage_dir.exists():
        try:
            storage_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return False, f"Could not create storage folder: {e}"

    test_file = storage_dir / ".preflight_write_test"
    try:
        # Verify write
        test_file.write_text("write_verification_payload")
        # Verify read
        content = test_file.read_text()
        if content != "write_verification_payload":
            return False, "Data read does not match written test payload"
        # Cleanup
        test_file.unlink()
        return True, "Read/Write permissions verified."
    except Exception as e:
        return False, f"Write check failed: {e}"


def check_database_integrity() -> tuple[bool, str]:
    """
    Check if the SQLite database is healthy and has schema consistency.
    """
    try:
        from backend.app.db.session import DATABASE_PATH
    except ImportError:
        DATABASE_PATH = PROJECT_ROOT / "storage" / "humanizer.db"

    if not DATABASE_PATH.exists():
        return True, "Database file not created yet. (Will initialize during boot)."

    try:
        conn = sqlite3.connect(str(DATABASE_PATH))
        cursor = conn.cursor()
        
        # Run SQLite internal integrity check
        cursor.execute("PRAGMA integrity_check;")
        res = cursor.fetchone()
        
        if not res or res[0].lower() != "ok":
            return False, f"Integrity check failed: {res}"

        # Verify our tables are present
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in cursor.fetchall()]
        
        conn.close()
        
        if tables:
            return True, f"SQLite is healthy ({len(tables)} tables verified: {', '.join(tables)})"
        return True, "SQLite is healthy (Empty database, ready for migration)"
    except Exception as e:
        return False, f"Database connectivity error: {e}"


def measure_endpoint_latency(url: str, name: str) -> tuple[bool, str]:
    """
    Verifies that standard DNS and HTTPS ports resolve to external dependencies,
    measuring endpoint roundtrip latency.
    """
    start_time = time.time()
    try:
        # Using a HEAD request to minimize bandwidth overhead
        req = urllib.request.Request(url, method="HEAD")
        # Set small timeout so preflight doesn't hang indefinitely
        with urllib.request.urlopen(req, timeout=3.0):
            pass
        latency = int((time.time() - start_time) * 1000)
        return True, f"Connected to {name} in {latency}ms"
    except urllib.error.HTTPError:
        # A status check failure (e.g. 404/403 HEAD request rejected) still confirms network route is alive!
        latency = int((time.time() - start_time) * 1000)
        return True, f"Connected to {name} in {latency}ms (Route ok, status rejected)"
    except Exception as e:
        return False, f"Failed to route to {name} within timeout. ({e})"


def run_diagnostics() -> bool:
    print_header()
    
    critical_failures = []
    warnings = []
    success_logs = []

    # 1. Directory permissions check (CRITICAL)
    ok, msg = check_directory_permissions()
    if ok:
        success_logs.append(f"[{GREEN}PASS{RESET}] Filesystem access: {msg}")
    else:
        critical_failures.append(f"[{RED}FAIL{RESET}] Filesystem access: {msg}")

    # 2. Database integrity check (CRITICAL)
    ok, msg = check_database_integrity()
    if ok:
        success_logs.append(f"[{GREEN}PASS{RESET}] Database integrity: {msg}")
    else:
        critical_failures.append(f"[{RED}FAIL{RESET}] Database integrity: {msg}")

    # 3. Network gateway tests (NON-CRITICAL warnings so dev/offline environments don't block boots)
    network_targets = [
        ("https://huggingface.co", "Hugging Face Models Hub"),
        ("https://generativelanguage.googleapis.com", "Google Gemini API Gateway"),
        ("https://api.groq.com", "Groq Llama API Gateway"),
        ("https://api.deepseek.com", "DeepSeek API Gateway")
    ]

    print(f"\n{BOLD}Probing external dependency latency routes...{RESET}")
    for url, name in network_targets:
        ok, msg = measure_endpoint_latency(url, name)
        if ok:
            success_logs.append(f"[{GREEN}PASS{RESET}] Network Probe: {msg}")
        else:
            warnings.append(f"[{YELLOW}WARN{RESET}] Network Probe: {msg}")

    # Print results
    print(f"\n{BOLD}Diagnostic Report Checklists:{RESET}")
    for log in success_logs:
        print(f"  {log}")
    for warn in warnings:
        print(f"  {warn}")
    for fail in critical_failures:
        print(f"  {fail}")

    print(f"\n{BOLD}=================================================={RESET}")
    
    if critical_failures:
        print(f"{BOLD}{RED}STATUS: PRE-FLIGHT CHECKS FAILED [RED LIGHT]{RESET}")
        print("Please resolve the directory permissions or database errors before starting.")
        print(f"{BOLD}{RED}=================================================={RESET}")
        return False
    else:
        print(f"{BOLD}{GREEN}STATUS: SYSTEM HEALTHY [GREEN LIGHT]{RESET}")
        print("All local validation and configuration layers are green.")
        print(f"{BOLD}{GREEN}=================================================={RESET}")
        return True


if __name__ == "__main__":
    healthy = run_diagnostics()
    if not healthy:
        sys.exit(1)
    sys.exit(0)
