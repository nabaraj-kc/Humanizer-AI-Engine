import asyncio
import uuid
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent))

from backend.app.services.prompt_factory import PromptFactory

async def print_prompt():
    run_id = "c79c6ead-6de2-40b8-813b-9baa22f68824"
    factory = PromptFactory()
    try:
        p = await factory.compile_system_prompt(run_id)
        print(p)
    except Exception as e:
        print("Error:", e)

asyncio.run(print_prompt())
