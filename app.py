import os
import requests
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# 1. Включаем CORS для VS Code
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.environ.get("GROQ_API_KEY")
if not API_KEY:
    raise ValueError("GROQ_API_KEY is missing!")

BASE_GROQ_URL = "https://api.groq.com/openai/v1"

# 2. Эндпоинт здоровья (ОБЯЗАТЕЛЬНО ПЕРВЫМ!)
@app.get("/health")
def health_check():
    return {"status": "ok", "service": "groq-proxy"}

# 3. Универсальный прокси (ловит всё остальное)
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(path: str, request: Request):
    # Отвечаем на предпроверку OPTIONS
    if request.method == "OPTIONS":
        return Response(status_code=200)

    try:
        target_url = f"{BASE_GROQ_URL}/{path}"
        body = await request.body()
        
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        groq_resp = requests.post(
            target_url,
            data=body,
            headers=headers,
            stream=True,
            timeout=(10, 180)
        )
        
        if groq_resp.status_code >= 400:
            return Response(
                content=groq_resp.content,
                status_code=groq_resp.status_code,
                media_type="application/json"
            )
            
        return StreamingResponse(
            groq_resp.iter_content(chunk_size=1024),
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
