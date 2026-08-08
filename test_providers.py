import asyncio
import sys
from pathlib import Path

# Resolve project root path
sys.path.append(str(Path(__file__).resolve().parent))

from backend.app.core.config import get_settings
from backend.app.services.openrouter_provider import OpenRouterProvider
from backend.app.services.google_provider import GoogleGeminiProvider
from backend.app.services.groq_provider import GroqProvider
from backend.app.services.deepseek_provider import DeepSeekProvider

async def test_all_providers():
    settings = get_settings()
    print("=== Configuration Keys ===")
    print(f"OpenRouter key set: {bool(settings.OPENROUTER_API_KEY)} (Starts with: {settings.OPENROUTER_API_KEY[:10] if settings.OPENROUTER_API_KEY else 'N/A'})")
    print(f"Google key set: {bool(settings.GOOGLE_API_KEY)} (Starts with: {settings.GOOGLE_API_KEY[:10] if settings.GOOGLE_API_KEY else 'N/A'})")
    print(f"Groq key set: {bool(settings.GROQ_API_KEY)} (Starts with: {settings.GROQ_API_KEY[:10] if settings.GROQ_API_KEY else 'N/A'})")
    print(f"DeepSeek key set: {bool(settings.DEEPSEEK_API_KEY)} (Starts with: {settings.DEEPSEEK_API_KEY[:10] if settings.DEEPSEEK_API_KEY else 'N/A'})")
    print()

    system_prompt = "You are a helpful assistant. Rewrite the user's message to make it sound highly professional and natural. Preserve all placeholders like __CITATION_0__."
    user_text = "Standard neural networks often struggle to maintain visual consistency when processing PDF documents. __CITATION_0__ has shown some progress, but layout shifts remain an issue."

    # 1. OpenRouter
    print("--- Testing OpenRouter (llama-3.3-70b-instruct:free) ---")
    try:
        prov = OpenRouterProvider()
        res = await prov.execute_text_rewrite(system_prompt, user_text)
        print(f"SUCCESS! Output:\n{res}\n")
    except Exception as e:
        print(f"FAILED: {e}\n")

    # 2. Google Gemini Flash
    print("--- Testing Google Gemini (gemini-2.0-flash) ---")
    try:
        prov = GoogleGeminiProvider(model_name="gemini-2.0-flash")
        res = await prov.execute_text_rewrite(system_prompt, user_text)
        print(f"SUCCESS! Output:\n{res}\n")
    except Exception as e:
        print(f"FAILED: {e}\n")

    # 3. Groq
    print("--- Testing Groq ---")
    try:
        prov = GroqProvider()
        res = await prov.execute_text_rewrite(system_prompt, user_text)
        print(f"SUCCESS! Output:\n{res}\n")
    except Exception as e:
        print(f"FAILED: {e}\n")

    # 4. DeepSeek
    print("--- Testing DeepSeek ---")
    try:
        prov = DeepSeekProvider()
        res = await prov.execute_text_rewrite(system_prompt, user_text)
        print(f"SUCCESS! Output:\n{res}\n")
    except Exception as e:
        print(f"FAILED: {e}\n")

if __name__ == "__main__":
    asyncio.run(test_all_providers())
