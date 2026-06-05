import os
import requests
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

app = FastAPI()

# Получаем ключ из секрета HF Space
API_KEY = os.environ.get("GROQ_API_KEY")
if not API_KEY:
    raise ValueError("GROQ_API_KEY secret is not set!")

BASE_GROQ_URL = "https://api.groq.com/openai/v1"

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(path: str, request: Request):
    try:
        # Собираем целевой URL
        target_url = f"{BASE_GROQ_URL}/{path}"
        
        # Получаем тело запроса от Continue
        body = await request.body()
        
        # Заголовки для Groq
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        # Делаем запрос к Groq с явным стримингом и таймаутами
        groq_resp = requests.post(
            target_url,
            data=body,
            headers=headers,
            stream=True,          # ВАЖНО: включаем поток
            timeout=(10, 180)     # 10с на коннект, 180с на чтение (для тяжелых моделей)
        )
        
        # Если Groq вернул ошибку (4xx/5xx), отдаем её как есть
        if groq_resp.status_code >= 400:
            return Response(
                content=groq_resp.content,
                status_code=groq_resp.status_code,
                media_type="application/json"
            )
        
        # Возвращаем поток с правильными заголовками
        return StreamingResponse(
            groq_resp.iter_content(chunk_size=1024),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # КРИТИЧЕСКИ ВАЖНО для HF Spaces!
                "Access-Control-Allow-Origin": "*"
            }
        )
        
    except requests.exceptions.Timeout as e:
        return Response(
            content=f'{{"error": "Gateway Timeout: {str(e)}"}}',
            status_code=504,
            media_type="application/json"
        )
    except requests.exceptions.ConnectionError as e:
        return Response(
            content=f'{{"error": "Connection Error: {str(e)}"}}',
            status_code=502,
            media_type="application/json"
        )
    except Exception as e:
        return Response(
            content=f'{{"error": "Internal Server Error: {str(e)}"}}',
            status_code=500,
            media_type="application/json"
        )

# Эндпоинт для проверки здоровья
@app.get("/health")
def health_check():
    return {"status": "ok", "service": "groq-proxy"}