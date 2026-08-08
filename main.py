"""
main.py
=======
Unified System Application Bootstrapper.
Initializes runtime folders, validates environment variables, configures and seeds
the database schema, and boots the FastAPI web application server on an available port.
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

# Hotpatch asyncio.Timeout and asyncio.timeout for aiohttp/anyio compatibility in Python 3.11 alpha
import asyncio

class CustomTimeout:
    def __init__(self, delay_or_deadline):
        self.delay = delay_or_deadline
        self._task = None
        self._timeout_handler = None
        self._expired = False

    def when(self):
        return self.delay

    def reschedule(self, when):
        self.delay = when

    def expired(self):
        return self._expired

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    async def __aenter__(self):
        if self.delay is None:
            return self
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return self
        self._task = asyncio.current_task(loop)
        self._timeout_handler = loop.call_later(self.delay, self._trigger_timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._timeout_handler is not None:
            self._timeout_handler.cancel()
        if exc_type is asyncio.CancelledError and self._expired:
            raise asyncio.TimeoutError() from None
        return False

    def _trigger_timeout(self):
        self._expired = True
        if self._task is not None:
            self._task.cancel()

if not hasattr(asyncio, "Timeout"):
    asyncio.Timeout = CustomTimeout

if not hasattr(asyncio, "timeout"):
    asyncio.timeout = CustomTimeout

import os
import sys
import socket
import logging
import asyncio
from pathlib import Path
import uvicorn

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Setup logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("humanizer_bootloader")


def check_env_variables() -> bool:
    """
    Check if required environment variables are set in the .env or system environment.
    Logs warning messages for missing values.
    """
    required_vars = [
        "DATABASE_URL",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "DEEPSEEK_API_KEY",
        "JWT_SECRET_KEY"
    ]
    missing = []
    
    # Load dotenv if present
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        logger.info("python-dotenv not installed. Relying on system environment variables.")

    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)

    if missing:
        logger.warning(f"Missing environment variables in runtime context: {', '.join(missing)}")
        return False
    
    logger.info("All required configuration environment variables verified.")
    return True


def verify_directories():
    """
    Ensure the database storage folder is present on the filesystem.
    """
    storage_dir = PROJECT_ROOT / "storage"
    if not storage_dir.exists():
        logger.info(f"Creating missing storage directory at: {storage_dir}")
        storage_dir.mkdir(parents=True, exist_ok=True)
    else:
        logger.info(f"Database storage directory verified at: {storage_dir}")


async def initialize_system_database():
    """
    Calls the database schema initialization and seeding routines.
    """
    try:
        from backend.app.db.init_db import initialize_database
        logger.info("Initializing SQLite database tables and seeding defaults...")
        await initialize_database(verbose=True)
        logger.info("Database successfully synchronized.")
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}", exc_info=True)
        sys.exit(1)


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """
    Check if a specific port is currently bound by another socket.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def find_available_port(start_port: int = 8000, host: str = "127.0.0.1") -> int:
    """
    Locates the next free port starting from the default configuration.
    """
    port = start_port
    while is_port_in_use(port, host):
        logger.warning(f"Port {port} is occupied. Scanning for next available socket...")
        port += 1
    return port


async def main():
    logger.info("Initializing Humanizer AI System pre-boot controls...")
    
    # 1. Check folder layout
    verify_directories()

    # 2. Check environment credentials
    check_env_variables()

    # 3. Synchronize database schema and seed provider quotas
    await initialize_system_database()

    # 4. Resolve bind ports
    host = "127.0.0.1"
    start_port = 8000
    port = find_available_port(start_port, host)
    
    if port != start_port:
        logger.info(f"Port redirection: Binding FastAPI application to dynamic port: {port}")
    else:
        logger.info(f"Successfully bound port {port} for application routing.")

    # 5. Boot Uvicorn Server
    logger.info(f"Launching FastAPI web application server on http://{host}:{port} ...")
    
    # Run Uvicorn synchronously on the current loop (or spawn it)
    config = uvicorn.Config(
        app="backend.app.main:app",
        host=host,
        port=port,
        log_level="info",
        reload=False
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("System shutdown triggered by keyboard interrupt.")
    except Exception as e:
        logger.critical(f"System failed to boot: {e}", exc_info=True)
        sys.exit(1)
