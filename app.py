import os
import requests
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# 1. Включаем CORS для VS Code / Cursor
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Загружаем ключи из переменных окружения Render
GROQ_KEY = os.environ.get("GROQ_API_KEY")
CEREBRAS_KEY = os.environ.get("CEREBRAS_API_KEY")

if not GROQ_KEY:
    raise ValueError("GROQ_API_KEY is missing!")
if not CEREBRAS_KEY:
    raise ValueError("CEREBRAS_API_KEY is missing!")

# 3. Базовые URL провайдеров (БЕЗ /v1 на конце!)
PROVIDERS = {
    "groq": "https://api.groq.com/openai",
    "cerebras": "https://api.cerebras.ai"
}

# 4. Эндпоинт здоровья
@app.get("/health")
def health_check():
    return {"status": "ok", "service": "multi-proxy", "providers": ["groq", "cerebras"]}

# 5. Универсальный прокси с поддержкой UTF-8 и умным роутингом
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(path: str, request: Request):
    # Отвечаем на предпроверку OPTIONS
    if request.method == "OPTIONS":
        return Response(status_code=200)

    try:
        # Читаем тело запроса как сырые байты (сохраняет UTF-8 без искажений)
        body_bytes = await request.body()
        
        # Определяем целевого провайдера по умолчанию
        target_base = PROVIDERS["groq"]
        api_key = GROQ_KEY
        
        # Умный роутинг: если в теле запроса есть ID модели Cerebras — переключаемся
        cerebras_keywords = [b'gpt-oss-120b', b'zai-glm-4.7']
        if b'"model"' in body_bytes:
            for keyword in cerebras_keywords:
                if keyword in body_bytes:
                    target_base = PROVIDERS["cerebras"]
                    api_key = CEREBRAS_KEY
                    break
                    
        # Формируем целевой URL (добавляем /v1 и путь от клиента)
        target_url = f"{target_base}/v1/{path}"
        
        # Явно указываем UTF-8 в заголовке + передаем сырые байты
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json"
        }
        
        # Отправляем запрос на целевой API
        resp = requests.post(
            target_url,
            data=body_bytes,  # Передаем байты напрямую, без перекодировки
            headers=headers,
            stream=True,
            timeout=(10, 180)
        )
        
        # Если целевой API вернул ошибку — пробрасываем её клиенту
        if resp.status_code >= 400:
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type="application/json"
            )
            
        # Для streaming ответов (чат) используем StreamingResponse
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
        # Логируем ошибку и возвращаем понятный ответ
        print(f"Proxy error: {str(e)}")
        return Response(
            content=f'{{"error": "{str(e)}"}}',
            status_code=502,
            media_type="application/json"
        )
