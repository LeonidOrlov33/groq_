import os
import requests
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Включаем CORS для VS Code / Cursor
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ключи из переменных окружения Render
GROQ_KEY = os.environ.get("GROQ_API_KEY")
CEREBRAS_KEY = os.environ.get("CEREBRAS_API_KEY")

if not GROQ_KEY:
    raise ValueError("GROQ_API_KEY is missing!")
if not CEREBRAS_KEY:
    raise ValueError("CEREBRAS_API_KEY is missing!")

# Базовые URL провайдеров (БЕЗ /v1 на конце!)
PROVIDERS = {
    "groq": "https://api.groq.com/openai",
    "cerebras": "https://api.cerebras.ai"
}

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "multi-proxy", "providers": ["groq", "cerebras"]}

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(path: str, request: Request):
    if request.method == "OPTIONS":
        return Response(status_code=200)

    try:
        # Читаем тело запроса, чтобы определить модель
        body_bytes = await request.body()
        
        # Простая логика роутинга по названию модели
        target_base = PROVIDERS["groq"]
        api_key = GROQ_KEY
        
        if b'"model"' in body_bytes and b'llama3.1-405b' in body_bytes:
            target_base = PROVIDERS["cerebras"]
            api_key = CEREBRAS_KEY
            
        # Формируем целевой URL (добавляем /v1 и путь)
        target_url = f"{target_base}/v1/{path}"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        resp = requests.post(
            target_url,
            data=body_bytes,
            headers=headers,
            stream=True,
            timeout=(10, 180)
        )
        
        if resp.status_code >= 400:
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type="application/json"
            )
            
        return StreamingResponse(
            resp.iter_content(chunk_size=1024),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*"
            }
        )
        
    except Exception as e:
        return Response(
            content=f'{{"error": "{str(e)}"}}',
            status_code=502,
            media_type="application/json"
        )
