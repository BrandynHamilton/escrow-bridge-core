from fastapi import FastAPI, Request
import uvicorn
import sys
import json
from datetime import datetime

app = FastAPI()

def log(message):
    """Print with timestamp and flush to ensure it shows immediately."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)
    sys.stdout.flush()

@app.post("/my-webhook")
async def receive_webhook(request: Request):
    try:
        data = await request.json()
        log(f"📩 Webhook received: {json.dumps(data)}")
        return {"status": "ok", "received": data}
    except Exception as e:
        log(f"❌ Error processing webhook: {e}")
        return {"status": "error", "error": str(e)}, 400

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def catch_all(request: Request, path: str):
    """Catch-all endpoint to log all requests for debugging."""
    try:
        body = await request.body()
        log(f"📨 Received {request.method} request to /{path}")
        if body:
            log(f"   Body: {body.decode('utf-8')}")
        return {"message": "received"}
    except Exception as e:
        log(f"❌ Error in catch-all: {e}")
        return {"error": str(e)}, 400

if __name__ == "__main__":
    log("Starting webhook server on http://0.0.0.0:9201")
    uvicorn.run(app, host="0.0.0.0", port=9201, access_log=True)