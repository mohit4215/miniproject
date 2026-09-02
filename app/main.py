from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config, llm
from .auth import init_firebase
from .db import init_db
from .routers import admin, gamify, notebooks, notes, rooms

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="StudyPartner", version="1.0.0")

app.include_router(rooms.router)
app.include_router(notebooks.router)
app.include_router(notes.router)
app.include_router(gamify.router)
app.include_router(admin.router)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.middleware("http")
async def static_no_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.on_event("startup")
def on_startup():
    init_db()
    try:
        init_firebase()
    except Exception as exc:
        print(f"[warn] firebase init failed: {exc}")
    if not config.settings.dev_auth and config.settings.firebase_sa_json == "" \
            and config.settings.firebase_sa_path == "":
        print("[warn] No auth configured: DEV_AUTH is off and no Firebase service "
              "account is set. Logins will fail until one is provided.")


@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "llm": "mock" if llm.mock_mode() else "live",
        "dev_auth": config.settings.dev_auth,
    }


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    html = templates.get_template("index.html").render({
        "request": request,
        "firebase_config": config.settings.firebase_config,
        "dev_auth": config.settings.dev_auth,
        "llm_mock": llm.mock_mode(),
    })
    return HTMLResponse(html)
