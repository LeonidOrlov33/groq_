import os
import asyncio
import json
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
    "groq": ("api.groq.com", 443, "/openai/v1"),
    "cerebras": ("api.cerebras.ai", 443, "/v1")
}

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(path: str, request: Request):
    if request.method == "OPTIONS":
        return Response(status_code=200)

    try:
        # 1. Читаем тело как сырые байты
        body_bytes = await request.body()
        
        # 2. Определяем провайдера
        provider_name = "groq"
        api_key = GROQ_KEY
        
        if b'"model"' in body_bytes:
            for kw in [b'gpt-oss-120b', b'zai-glm-4.7']:
                if kw in body_bytes:
                    provider_name = "cerebras"
                    api_key = CEREBRAS_KEY
                    break
                    
        host, port, base_path = PROVIDERS[provider_name]
        target_path = f"{base_path}/{path}"
        
        # 3. Формируем HTTP-запрос ВРУЧНУЮ как строку ASCII
        # Это ГАРАНТИРОВАННО обходит все проверки ByteString
        http_request = (
            f"POST {target_path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Authorization: Bearer {api_key}\r\n"
            f"Content-Type: application/json; charset=utf-8\r\n"
            f"Accept: application/json\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: keep-alive\r\n"
            f"\r\n"
        ).encode('ascii')  # <-- Явное кодирование в ASCII
        
        # 4. Отправляем через raw TCP сокет
        reader, writer = await asyncio.open_connection(host, port, ssl=True)
        
        # Отправляем заголовки + тело
        writer.write(http_request + body_bytes)
        await writer.drain()
        
        # 5. Читаем ответ построчно до начала тела
        status_line = await reader.readline()
        headers = {}
        while True:
            line = await reader.readline()
            if line in (b'\r\n', b'\n', b''):
                break
            if b':' in line:
                key, val = line.split(b':', 1)
                headers[key.decode('ascii').strip().lower()] = val.decode('ascii').strip()
                
        status_code = int(status_line.split(b' ')[1])
        is_chunked = headers.get('transfer-encoding', '').lower() == 'chunked'
        content_length = int(headers.get('content-length', 0))
        
        # 6. Проброс ошибок
        if status_code >= 400:
            error_body = await reader.readexactly(content_length) if content_length > 0 else b''
            return Response(
                content=error_body,
                status_code=status_code,
                media_type="application/json"
            )
            
        # 7. Стриминг ответа
        async def stream_gen():
            if is_chunked:
                while True:
                    chunk_size_line = await reader.readline()
                    if not chunk_size_line or chunk_size_line == b'\r\n':
                        break
                    size = int(chunk_size_line.strip(), 16)
                    if size == 0:
                        break
                    chunk = await reader.readexactly(size)
                    yield chunk
                    await reader.readexactly(2)  # \r\n после чанка
            else:
                remaining = content_length
                while remaining > 0:
                    read_size = min(1024, remaining)
                    chunk = await reader.readexactly(read_size)
                    yield chunk
                    remaining -= len(chunk)
                    
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
