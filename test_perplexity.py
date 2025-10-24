import requests

API_KEY = ""
url = "https://api.perplexity.ai/chat/completions"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

data = {
    "model": "sonar-pro",
    "messages": [{"role": "user", "content": "Hello, are you working?"}]
}

print("DEBUG AUTH HEADER:", headers)
res = requests.post(url, headers=headers, json=data)
print(res.status_code, res.text)
