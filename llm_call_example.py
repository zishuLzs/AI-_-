import os
import requests

ONE_API_URL = os.getenv("ONE_API_URL", "https://one-api-other.nowcoder.com/v1/chat/completions")
ONE_API_KEY = "YOUR_ONE_API_KEY"
# 可用模型：doubao-seed-2-0-lite-260428-cmb / qwen3.6-flash
ONE_API_MODEL = "qwen3.6-flash"

resp = requests.post(
    ONE_API_URL,
    headers={
        "Authorization": f"Bearer {ONE_API_KEY}",
        "Content-Type": "application/json",
    },
    json={
        "model": ONE_API_MODEL,
        "messages": [
            {"role": "user", "content": "请用一句话解释为什么年金险可以对冲长寿风险。"}
        ],
        "temperature": 0,
        "stream": False,
    },
    timeout=60,
)

resp.raise_for_status()
print(resp.json()["choices"][0]["message"]["content"])
