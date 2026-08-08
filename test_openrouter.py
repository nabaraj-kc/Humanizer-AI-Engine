import urllib.request, json

req = urllib.request.Request(
    'https://openrouter.ai/api/v1/chat/completions',
    headers={
        'Authorization': 'Bearer os.getenv("OPENROUTER_API_KEY")',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://humanizer-ai.local'
    },
    data=json.dumps({
        'model':'meta-llama/llama-3.3-70b-instruct:free',
        'messages':[{'role':'user','content':'hello'}]
    }).encode()
)
try:
    urllib.request.urlopen(req)
except Exception as e:
    print(e.read().decode())
