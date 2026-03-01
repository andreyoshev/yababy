import json
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader
from loguru import logger

from app import db
from app.alice.handlers import handle
from app.alice.models import AliceRequestBody, AliceResponse
from app.config import TEMPLATES_DIR
from app.huckleberry import service as hb


class InterceptHandler(logging.Handler):
    """Route standard logging (uvicorn, etc.) through loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def setup_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.DEBUG, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        log = logging.getLogger(name)
        log.handlers = [InterceptHandler()]
        log.propagate = False


setup_logging()

jinja = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await db.init()
    logger.info("DB initialized at {}", db.DB_PATH)
    yield
    await db.close()


app = FastAPI(title="YaBaby Alice Skill", lifespan=lifespan)


@app.post("/alice/webhook")
async def alice_webhook(request: Request) -> AliceResponse:
    raw = await request.json()
    logger.info("Alice request:\n{}", json.dumps(raw, ensure_ascii=False, indent=2))

    body = AliceRequestBody(**raw)
    response = await handle(body)

    logger.info("Alice response: {}", response.response.text)
    return response


@app.get("/setup", response_class=HTMLResponse)
async def setup_page():
    tpl = jinja.get_template("setup.html")
    return tpl.render(pin=None, children=None, error=None, email=None)


@app.post("/setup", response_class=HTMLResponse)
async def setup_submit(email: str = Form(...), password: str = Form(...), timezone: str = Form("Europe/Moscow")):
    tpl = jinja.get_template("setup.html")
    try:
        refresh_token, children = await hb.authenticate(email, password, timezone=timezone)
    except Exception as e:
        logger.error("Huckleberry auth failed: {}", e)
        return tpl.render(pin=None, children=None, error="Не удалось войти. Проверьте email и пароль.", email=email)

    return tpl.render(
        pin=None, children=children, error=None,
        refresh_token=refresh_token, hb_email=email, timezone=timezone,
    )


@app.post("/setup/children", response_class=HTMLResponse)
async def setup_children(request: Request):
    tpl = jinja.get_template("setup.html")
    form = await request.form()
    refresh_token = form.get("refresh_token", "")
    hb_email = form.get("hb_email", "")
    timezone = form.get("timezone", "Europe/Moscow")
    count = int(form.get("count", "0"))

    children = []
    for i in range(count):
        uid = form.get(f"uid_{i}", "")
        hb_name = form.get(f"hb_name_{i}", "")
        voice_name = form.get(f"voice_name_{uid}", "").strip()
        if not voice_name:
            voice_name = hb_name
        children.append({"uid": uid, "name": hb_name, "voice_name": voice_name.lower()})

    pin = await db.create_pending_link(hb_email, refresh_token, children, timezone)
    logger.info("PIN {} created for {} with {} children (tz={})", pin, hb_email, len(children), timezone)
    return tpl.render(pin=pin, children=None, error=None)
