import os
import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# 1. CORS для VS Code / Cursor
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Ключи из переменных окружения Render
GROQ_KEY = os.environ.get("GROQ_API_KEY")
CEREBRAS_KEY = os.environ.get("CEREBRAS_API_KEY")

if not GROQ_KEY:
    raise ValueError("GROQ_API_KEY is missing!")
if not CEREBRAS_KEY:
    raise ValueError("CEREBRAS_API_KEY is missing!")

# 3. Базовые URL (БЕЗ /v1)
PROVIDERS = {
    "groq": "https://api.groq.com/openai",
    "cerebras": "https://api.cerebras.ai"
}

# 4. Health check
@app.get("/health")
def health_check():
    return {"status": "ok", "service": "multi-proxy", "providers": ["groq", "cerebras"]}

# 5. Универсальный прокси
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(path: str, request: Request):
    if request.method == "OPTIONS":
        return Response(status_code=200)

    try:
        # Читаем сырые байты — UTF-8 сохраняется идеально
        body_bytes = await request.body()
        
        # Роутинг по модели
        target_base = PROVIDERS["groq"]
        api_key = GROQ_KEY
        
        cerebras_keywords = [b'gpt-oss-120b', b'zai-glm-4.7']
        if b'"model"' in body_bytes:
            for keyword in cerebras_keywords:
                if keyword in body_bytes:
                    target_base = PROVIDERS["cerebras"]
                    api_key = CEREBRAS_KEY
                    break
                    
        target_url = f"{target_base}/v1/{path}"
        
        headers = dict(request.headers)
        # Обновляем заголовки авторизации и контента
        headers["authorization"] = f"Bearer {api_key}"
        headers["content-type"] = "application/json; charset=utf-8"
        # Удаляем заголовок host, чтобы не конфликтовал с целевым сервером
        headers.pop("host", None)
        
        # httpx отправляет content=bytes БЕЗ перекодировки!
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                target_url,
                content=body_bytes,  # <-- КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ
                headers=headers,
                timeout=httpx.Timeout(10.0, read=180.0),
                stream=True
            )
            
        if resp.status_code >= 400:
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type="application/json"
            )
            
        # Асинхронный стриминг
        async def stream_generator():
            async for chunk in resp.aiter_bytes(chunk_size=1024):
                yield chunk
                
        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*"
            }
        )
        
    except Exception as e:
        print(f"Proxy error: {str(e)}")
        return Response(
            content=f'{{"error": "{str(e)}"}}',
            status_code=502,
            media_type="application/json"
        )
