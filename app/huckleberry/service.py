from __future__ import annotations

import asyncio
import time
from functools import partial
from typing import Any

from huckleberry_api import HuckleberryAPI
from loguru import logger

from app import db


def _relative_time(ts: float) -> str:
    """Format a unix timestamp as a human-readable relative time in Russian."""
    diff = time.time() - ts
    if diff < 60:
        return "только что"
    minutes = int(diff // 60)
    hours = int(diff // 3600)
    if hours == 0:
        return f"{minutes} мин. назад"
    remaining_min = minutes - hours * 60
    if remaining_min > 0:
        return f"{hours} ч. {remaining_min} мин. назад"
    return f"{hours} ч. назад"


def _duration_text(seconds: float) -> str:
    """Format duration in seconds as human-readable Russian string."""
    minutes = int(seconds // 60)
    hours = int(minutes // 60)
    remaining_min = minutes - hours * 60
    if hours == 0:
        return f"{minutes} мин."
    if remaining_min > 0:
        return f"{hours} ч. {remaining_min} мин."
    return f"{hours} ч."


def _make_client(email: str, password: str, timezone: str) -> HuckleberryAPI:
    return HuckleberryAPI(email=email, password=password, timezone=timezone)


def _auth_and_get_children(email: str, password: str, timezone: str) -> tuple[str, list[dict]]:
    """Authenticate and return (refresh_token, children). Runs in thread."""
    api = _make_client(email, password, timezone)
    api.authenticate()
    children = api.get_children()
    return api.refresh_token, [{"uid": c["uid"], "name": c.get("name", "Baby")} for c in children]


def _restore_client(refresh_token: str, timezone: str) -> HuckleberryAPI:
    """Restore an authenticated client from a refresh token. Runs in thread."""
    api = HuckleberryAPI(email="", password="", timezone=timezone)
    api.refresh_token = refresh_token
    api.refresh_auth_token()
    return api


async def authenticate(email: str, password: str, timezone: str = "Europe/Moscow") -> tuple[str, list[dict]]:
    """Authenticate with Huckleberry. Returns (refresh_token, children)."""
    return await asyncio.to_thread(_auth_and_get_children, email, password, timezone)


async def _get_client(user: dict) -> HuckleberryAPI:
    """Get an authenticated HuckleberryAPI client for a user record."""
    api = await asyncio.to_thread(_restore_client, user["hb_refresh_token"], user.get("timezone", "Europe/Moscow"))
    if api.refresh_token and api.refresh_token != user["hb_refresh_token"]:
        await db.update_refresh_token(user["alice_user_id"], api.refresh_token)
    return api


def _name(user: dict) -> str:
    return (user.get("child_name") or "").capitalize()


async def start_sleep(user: dict) -> str:
    api = await _get_client(user)
    await asyncio.to_thread(api.start_sleep, user["selected_child_uid"])
    return f"{_name(user)} уснул. Записано."


async def complete_sleep(user: dict) -> str:
    api = await _get_client(user)
    await asyncio.to_thread(api.complete_sleep, user["selected_child_uid"])
    return f"{_name(user)} проснулся. Сон завершён."


async def log_diaper(user: dict, mode: str = "both", pee: bool = True, poo: bool = False) -> str:
    api = await _get_client(user)
    await asyncio.to_thread(
        partial(api.log_diaper, user["selected_child_uid"], mode=mode, pee=pee, poo=poo)
    )
    labels = {"pee": "пописал", "poo": "покакал", "both": "пописал и покакал", "dry": "сухой подгузник"}
    return f"{_name(user)} {labels.get(mode, mode)}. Записано."


async def log_bottle(user: dict, amount: float, bottle_type: str = "Formula", units: str = "ml") -> str:
    api = await _get_client(user)
    await asyncio.to_thread(
        partial(api.log_bottle_feeding, user["selected_child_uid"], amount=amount, bottle_type=bottle_type, units=units)
    )
    return f"{_name(user)} выпил {amount:.0f} мл. Записано."


async def start_feeding(user: dict, side: str = "left") -> str:
    api = await _get_client(user)
    await asyncio.to_thread(partial(api.start_feeding, user["selected_child_uid"], side=side))
    side_label = {"left": "левая", "right": "правая"}.get(side, side)
    return f"{_name(user)} кушает, {side_label} грудь. Записано."


async def complete_feeding(user: dict) -> str:
    api = await _get_client(user)
    await asyncio.to_thread(api.complete_feeding, user["selected_child_uid"])
    return f"{_name(user)} покушал. Записано."


def _read_status(api: HuckleberryAPI, child_uid: str) -> dict:
    """Read sleep/feed/diaper documents from Firestore. Runs in thread."""
    client = api._get_firestore_client()
    result: dict[str, Any] = {}

    sleep_doc = client.collection("sleep").document(child_uid).get()
    if sleep_doc.exists:
        result["sleep"] = sleep_doc.to_dict() or {}

    feed_doc = client.collection("feed").document(child_uid).get()
    if feed_doc.exists:
        result["feed"] = feed_doc.to_dict() or {}

    diaper_doc = client.collection("diaper").document(child_uid).get()
    if diaper_doc.exists:
        result["diaper"] = diaper_doc.to_dict() or {}

    return result


def _format_sleep_status(name: str, data: dict) -> str | None:
    sleep = data.get("sleep", {})
    timer = sleep.get("timer", {})
    prefs = sleep.get("prefs", {})

    if timer.get("active") and not timer.get("paused"):
        start_ms = timer.get("timerStartTime")
        if start_ms:
            duration = time.time() - start_ms / 1000
            return f"{name} спит уже {_duration_text(duration)}."
        return f"{name} сейчас спит."

    last = prefs.get("lastSleep")
    if last and last.get("start") and last.get("duration"):
        woke_up_ts = last["start"] + last["duration"]
        slept_sec = last["duration"]
        return f"{name} проснулся {_relative_time(woke_up_ts)}, спал {_duration_text(slept_sec)}."

    return None


def _format_feed_status(data: dict) -> str | None:
    feed = data.get("feed", {})
    prefs = feed.get("prefs", {})

    last_nursing = prefs.get("lastNursing", {})
    last_bottle = prefs.get("lastBottle", {})

    nursing_ts = last_nursing.get("start", 0)
    bottle_ts = last_bottle.get("start", 0)

    if nursing_ts == 0 and bottle_ts == 0:
        return None

    if bottle_ts >= nursing_ts and bottle_ts > 0:
        amount = last_bottle.get("bottleAmount", 0)
        units = last_bottle.get("bottleUnits", "ml")
        if amount:
            return f"Последнее кормление {_relative_time(bottle_ts)}, бутылочка {amount:.0f} {units}."
        return f"Последнее кормление {_relative_time(bottle_ts)}, бутылочка."

    if nursing_ts > 0:
        duration = last_nursing.get("duration", 0)
        if duration and duration > 60:
            return f"Последнее кормление {_relative_time(nursing_ts)}, грудь {_duration_text(duration)}."
        return f"Последнее кормление {_relative_time(nursing_ts)}, грудь."

    return None


def _format_diaper_status(data: dict) -> str | None:
    diaper = data.get("diaper", {})
    prefs = diaper.get("prefs", {})
    last = prefs.get("lastDiaper", {})

    if not last.get("start"):
        return None

    modes = {"pee": "пописал", "poo": "покакал", "both": "пописал и покакал", "dry": "сухой"}
    mode_label = modes.get(last.get("mode", ""), last.get("mode", ""))
    return f"Подгузник {_relative_time(last['start'])}, {mode_label}."


async def get_status(user: dict, scope: str = "full") -> str:
    """Get status info. scope: 'full', 'sleep', 'feed', 'diaper'."""
    api = await _get_client(user)
    data = await asyncio.to_thread(_read_status, api, user["selected_child_uid"])
    name = _name(user)

    if scope == "sleep":
        return _format_sleep_status(name, data) or f"Нет данных о сне {name}."

    if scope == "feed":
        return _format_feed_status(data) or f"Нет данных о кормлении {name}."

    if scope == "diaper":
        return _format_diaper_status(data) or f"Нет данных о подгузниках {name}."

    parts = [
        _format_sleep_status(name, data),
        _format_feed_status(data),
        _format_diaper_status(data),
    ]
    result = " ".join(p for p in parts if p)
    return result or f"Нет данных о {name}."
