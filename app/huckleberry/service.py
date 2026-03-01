from __future__ import annotations

import asyncio
from functools import partial
from typing import Any

from huckleberry_api import HuckleberryAPI
from loguru import logger

from app import db


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
