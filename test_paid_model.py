import urllib.request
import json

req = urllib.request.Request(
    'https://openrouter.ai/api/v1/chat/completions',
    headers={
        'Authorization': 'Bearer os.getenv("OPENROUTER_API_KEY")',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://humanizer-ai.local'
    },
    data=json.dumps({
        'model': 'meta-llama/llama-3.3-70b-instruct',
        'messages': [{'role': 'user', 'content': 'hello'}]
    }).encode()
)
try:
    with urllib.request.urlopen(req) as response:
        res_data = response.read().decode()
        print("SUCCESS:")
        print(res_data)
except Exception as e:
    if hasattr(e, "read"):
        print("FAILED:")
        print(e.read().decode())
    else:
        print("FAILED:", e)
