# Humanizer AI Backend Package

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

# Hotpatch asyncio.Timeout and asyncio.timeout for aiohttp compatibility in Python 3.11 alpha
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

    # Sync context manager methods
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    # Async context manager methods
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

