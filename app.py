import os
import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ключи
GROQ_KEY = os.environ.get("GROQ_API_KEY")
CEREBRAS_KEY = os.environ.get("CEREBRAS_API_KEY")

if not GROQ_KEY or not CEREBRAS_KEY:
    raise ValueError("Missing API keys!")

PROVIDERS = {
    "groq": "https://api.groq.com/openai",
    "cerebras": "https://api.cerebras.ai"
}

# Разрешенные заголовки (только ASCII-safe)
ALLOWED_HEADERS = {
    'authorization', 'content-type', 'accept', 'user-agent',
    'x-request-id', 'traceparent', 'baggage'
}

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(path: str, request: Request):
    if request.method == "OPTIONS":
        return Response(status_code=200)

    try:
        # Читаем сырые байты тела
        body_bytes = await request.body()
        
        # Роутинг
        target_base = PROVIDERS["groq"]
        api_key = GROQ_KEY
        
        if b'"model"' in body_bytes:
            for kw in [b'gpt-oss-120b', b'zai-glm-4.7']:
                if kw in body_bytes:
                    target_base = PROVIDERS["cerebras"]
                    api_key = CEREBRAS_KEY
                    break
                    
        target_url = f"{target_base}/v1/{path}"
        
        # ЖЕСТКАЯ ФИЛЬТРАЦИЯ ЗАГОЛОВКОВ
        # Берем ТОЛЬКО разрешенные заголовки и кодируем их в ASCII
        safe_headers = {}
        for key, value in request.headers.items():
            lower_key = key.lower()
            if lower_key in ALLOWED_HEADERS:
                # Принудительно кодируем значение в ASCII, заменяя недопустимые символы
                try:
                    safe_headers[key] = value.encode('ascii').decode('ascii')
                except (UnicodeEncodeError, UnicodeDecodeError):
                    # Если заголовок содержит кириллицу/эмодзи — пропускаем его полностью
                    continue
        
        # Добавляем обязательные заголовки
        safe_headers["Authorization"] = f"Bearer {api_key}"
        safe_headers["Content-Type"] = "application/json; charset=utf-8"
        safe_headers["Accept"] = "application/json"
        safe_headers["Content-Length"] = str(len(body_bytes))
        
        # Отправляем через httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                target_url,
                content=body_bytes,
                headers=safe_headers,  # <-- Только безопасные ASCII заголовки!
                timeout=httpx.Timeout(10.0, read=180.0)
            )
            
        # Проброс ошибок
        if resp.status_code >= 400:
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type="application/json"
            )
            
        # Стриминг
        async def stream_gen():
            async for chunk in resp.aiter_bytes(chunk_size=1024):
                yield chunk
                
        return StreamingResponse(
            stream_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*"
            }
        )
        
    except Exception as e:
        print(f"Proxy error: {e}")
        return Response(
            content=f'{{"error": "{str(e)}"}}',
            status_code=502,
            media_type="application/json"
        )
