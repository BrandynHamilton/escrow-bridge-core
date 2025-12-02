# API Key Authentication Setup

This guide explains how to use the new API key system for the Escrow Bridge.

## Database Setup

The APIKey model has been added to `escrow_bridge/db/models.py` with the following features:

- **Secure Storage**: API keys are hashed using SHA256 before storage
- **Key Generation**: 96-character hex keys (48 bytes)
- **Key Management**: Generate, list, deactivate (soft delete)
- **Usage Tracking**: Tracks when each key was last used

## API Endpoints

### 1. Generate New API Key

**POST** `/api-keys/generate`

```bash
curl -X POST http://localhost:4284/api-keys/generate \
  -H "Content-Type: application/json" \
  -d '{"name": "Production API Key"}'
```

**Response:**
```json
{
  "key": "abc123def456...",  // Only shown once!
  "api_key": {
    "id": 1,
    "name": "Production API Key",
    "created_at": "2024-12-01T12:00:00",
    "last_used_at": null,
    "is_active": true
  }
}
```

⚠️ **Important**: Save the `key` value immediately - it won't be shown again!

### 2. List API Keys

**GET** `/api-keys`

```bash
curl http://localhost:4284/api-keys
```

**Response:**
```json
{
  "api_keys": [
    {
      "id": 1,
      "name": "Production API Key",
      "created_at": "2024-12-01T12:00:00",
      "last_used_at": "2024-12-01T12:30:00",
      "is_active": true
    }
  ]
}
```

### 3. Deactivate API Key

**DELETE** `/api-keys/{key_id}`

```bash
curl -X DELETE http://localhost:4284/api-keys/1
```

**Response:**
```json
{
  "message": "API key 'Production API Key' has been deactivated"
}
```

## Using API Keys

### With `/request_payment` Endpoint

Include the API key in the `X-API-Key` header:

```bash
curl -X POST http://localhost:4284/request_payment \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key_here" \
  -d '{
    "amount": 100,
    "receiver": "0x1234...",
    "email": "user@example.com",
    "network": "base-sepolia"
  }'
```

Or in Python:

```python
import requests

api_key = "your_api_key_here"
headers = {"X-API-Key": api_key}

response = requests.post(
    "http://localhost:4284/request_payment",
    json={
        "amount": 100,
        "receiver": "0x1234...",
        "email": "user@example.com",
        "network": "base-sepolia"
    },
    headers=headers
)

print(response.json())
```

## Database Schema

The `api_keys` table contains:

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| name | VARCHAR(255) | User-friendly name |
| key_hash | VARCHAR(64) | SHA256 hash of the API key |
| created_at | DATETIME | Creation timestamp |
| last_used_at | DATETIME | Last usage timestamp |
| is_active | BOOLEAN | Active/inactive status |

## Security Notes

1. **Keys are hashed**: Never stored in plaintext
2. **One-time display**: Key is only shown when generated
3. **Soft delete**: Keys are deactivated, not deleted
4. **Usage tracking**: All key usage is logged with `last_used_at`
5. **No key retrieval**: Once generated, the plaintext key cannot be retrieved

## Implementation Details

### In main.py

The following has been added:

1. **Pydantic Models**:
   - `APIKeyCreateRequest`: For generating keys
   - `APIKeyResponse`: For listing keys
   - `APIKeyGenerateResponse`: For generation response

2. **Dependency Function**:
   ```python
   async def validate_api_key(x_api_key: str = Header(None)) -> APIKey:
   ```
   Use with `Depends(validate_api_key)` on protected endpoints

3. **Endpoints**:
   - `POST /api-keys/generate` - Create new key
   - `GET /api-keys` - List all keys
   - `DELETE /api-keys/{key_id}` - Deactivate key

### In models.py

The `APIKey` class provides:

- `APIKey.generate_key()` - Generate a new key
- `APIKey.hash_key(key)` - Hash a key for storage
- `APIKey.create(name, session)` - Create and save a key
- `APIKey.verify_key(key, session)` - Verify a key and update `last_used_at`

## Migration

If you have an existing database:

1. **Restart the application**: The new `api_keys` table will be created automatically
2. **Or run manually**:
   ```python
   from escrow_bridge.db import init_db
   init_db()  # Creates all tables including api_keys
   ```

## Testing

```bash
# 1. Generate a key
KEY_RESPONSE=$(curl -X POST http://localhost:4284/api-keys/generate \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Key"}')

API_KEY=$(echo $KEY_RESPONSE | jq -r '.key')

# 2. Use the key
curl -X POST http://localhost:4284/request_payment \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "amount": 50,
    "receiver": "0x1234...",
    "email": "test@example.com",
    "network": "base-sepolia"
  }'

# 3. List keys
curl http://localhost:4284/api-keys

# 4. Delete the key
curl -X DELETE http://localhost:4284/api-keys/1
```

## Next Steps

1. Ensure `DATABASE_URL` is set in your environment
2. Restart the backend service
3. Generate your first API key
4. Use it in your integration
