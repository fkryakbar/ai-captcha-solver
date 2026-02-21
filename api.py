import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Header, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict
from dotenv import load_dotenv
import asyncio
from selenium import webdriver
from main import solve_recaptcha_v2_for_api

load_dotenv()

API_KEY = os.getenv("API_KEY")
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

templates = Jinja2Templates(directory="templates")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown

app = FastAPI(title="AI Captcha ByPass API", lifespan=lifespan)

class SolveRequest(BaseModel):
    sitekey: str
    url: str | None = None
    siteurl: str | None = None
    model: str | None = None
    stream: bool = False
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "sitekey": "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI",
                "siteurl": "https://emis.kemenag.go.id/",
                "model": "gemini-2.5-flash",
                "stream": False
            }
        }
    )

def verify_api_key(x_api_key: str | None = Header(default=None)):
    if API_KEY:
        if not x_api_key or x_api_key != API_KEY:
            raise HTTPException(status_code=401, detail="Invalid API Key")
    return x_api_key

@app.get("/local_captcha", response_class=HTMLResponse)
async def local_captcha(request: Request, sitekey: str, siteurl: str | None = None):
    """
    Serve a local HTML page populated with the sitekey to solve the captcha locally.
    """
    return templates.TemplateResponse(
        request=request, 
        name="captcha.html", 
        context={"sitekey": sitekey, "siteurl": siteurl}
    )

def run_solver(target_url: str, provider: str, model: str, log_cb=None):
    import os
    os.makedirs('screenshots', exist_ok=True)
    
    options = webdriver.FirefoxOptions()
    options.add_argument("--headless") # Headless mode enabled
    driver = webdriver.Firefox(options=options)
    try:
        # We pass log_cb downwards to stream console logs if necessary
        token, total_tokens = solve_recaptcha_v2_for_api(driver, target_url, provider=provider, model=model, log_cb=log_cb)
        return token, total_tokens
    finally:
        driver.quit()

@app.post("/api/solve")
async def solve_captcha(req: SolveRequest, request: Request, api_key: str | None = Depends(verify_api_key)):
    """
    Endpoint to solve reCAPTCHA v2 using Gemini models.
    """
    # 1. Validation
    # Use default model if not provided
    selected_model = req.model if req.model else DEFAULT_MODEL
    
    if not selected_model.startswith("gemini"):
        raise HTTPException(status_code=400, detail="Only gemini models are supported per requirements.")
        
    # 2. Determine target URL
    if not req.url:
        # Use localhost unconditionally so the headless docker container doesn't need to try routing
        # out to the public internet/external IP to hit its own local_captcha endpoint.
        # MUST use localhost as reCAPTCHA domain validation whitelists localhost but blocks 127.0.0.1
        base_url = "http://localhost:8000"
        target_url = f"{base_url}/local_captcha?sitekey={req.sitekey}"
        if req.siteurl:
            import urllib.parse
            target_url += f"&siteurl={urllib.parse.quote(req.siteurl)}"
    else:
        target_url = req.url
        
    # 3. Solver execution routing
    loop = asyncio.get_event_loop()
    
    if req.stream:
        import json
        queue = asyncio.Queue()
        
        def push_log(msg):
            # Non-blocking sync-to-async boundary bridge 
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "progress", "message": msg})
            
        def background_solve():
            try:
                token, total_tokens = run_solver(target_url, "gemini", selected_model, log_cb=push_log)
                if token:
                    loop.call_soon_threadsafe(queue.put_nowait, {"type": "success", "token": token, "total_tokens_used": total_tokens})
                else:
                    loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": "Failed to extract token"})
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": str(e)})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None) # EOF sentinel

        # Start solver thread
        import threading
        t = threading.Thread(target=background_solve)
        t.start()
        
        async def event_generator():
            while True:
                data = await queue.get()
                if data is None:
                    # Connection closed or finished
                    break
                yield f"data: {json.dumps(data)}\n\n"
                
        return StreamingResponse(event_generator(), media_type="text/event-stream")
        
    else:
        # Non-streaming Standard JSON response
        token, total_tokens = await loop.run_in_executor(None, run_solver, target_url, "gemini", selected_model, None)
        
        if token:
            print(f"Total Gemini tokens used for this solve: {total_tokens}")
            return {"status": "success", "token": token, "total_tokens_used": total_tokens}
        else:
            raise HTTPException(status_code=500, detail="Failed to solve captcha or extract token.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
