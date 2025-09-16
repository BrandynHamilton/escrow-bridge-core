from fastapi import FastAPI, Request
import uvicorn

app = FastAPI()

@app.post("/my-webhook")
async def receive_webhook(request: Request):
    data = await request.json()
    print("📩 Webhook received:", data)
    return {"status": "ok", "received": data}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9200)
