import os
from dotenv import load_dotenv
import requests

load_dotenv()

ADMIN_KEY = os.getenv("ADMIN_KEY")
BASE_URL = os.getenv("BASE_URL", "http://localhost:4284")

headers = {"x-admin-key": ADMIN_KEY} if ADMIN_KEY else {}

print(f'Using ADMIN_KEY: {"set" if ADMIN_KEY else "not set"}')
print(f'Using BASE_URL: {BASE_URL}')

# Generate API key with a name
payload = {"name": "Test API Key"}
response = requests.post(
    f"{BASE_URL}/admin/generate_api_key",
    json=payload,
    headers=headers
)
response.raise_for_status()
data = response.json()

print("✅ API Key Generated Successfully!")
print(f"Key: {data['key']}")
print(f"API Key Details: {data['api_key']}")