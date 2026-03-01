import json
import logging
import sys

from fastapi import FastAPI, Request
from loguru import logger

from app.alice.models import AliceResponse, Response


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

app = FastAPI(title="YaBaby Alice Skill")


@app.post("/alice/webhook")
async def alice_webhook(request: Request) -> AliceResponse:
    body = await request.json()
    logger.info("Alice request:\n{}", json.dumps(body, ensure_ascii=False, indent=2))

    is_new = body.get("session", {}).get("new", False)
    text = "Привет! Я пока учусь." if is_new else "Я тебя слышу, но пока не умею отвечать."

    return AliceResponse(response=Response(text=text))
