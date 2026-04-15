from __future__ import annotations

import json
import re

from loguru import logger

from app import db
from app.alice.models import AliceRequestBody, AliceResponse, reply
from app.huckleberry import service as hb

SETUP_URL = "yababy.oshev.me/setup"


def _cap(name: str) -> str:
    return name.capitalize() if name else name

HELP_TEXT = (
    "Я могу записывать сон, подгузники и кормление.\n"
    "Скажи, например: уснул, проснулся, пописал, покакал, "
    "выпил 60 миллилитров, кушает левую, покушал.\n"
    "А ещё: статус, когда ел, сколько не спит."
)


async def handle(body: AliceRequestBody) -> AliceResponse:
    user_id = body.alice_user_id
    if not user_id:
        return reply("Не удалось определить пользователя. Попробуйте позже.")

    user = await db.get_user(user_id)
    cmd = body.command

    if _is_pin(cmd):
        return await _handle_link(user_id, cmd)

    if user is None:
        return _ask_to_link()

    if not user.get("selected_child_uid"):
        return await _try_select_child(user, cmd)

    if body.session.new and not cmd:
        return reply(f"Привет! Слежу за {_cap(user['child_name'])}. {HELP_TEXT}", end_session=False)

    intent_name = _detect_intent(body)
    logger.info("Detected intent: {} for command: {}", intent_name, cmd)

    try:
        return await _dispatch(intent_name, body, user)
    except Exception as e:
        logger.exception("Error handling intent {}", intent_name)
        return reply(f"Ошибка: {e}", end_session=False)


def _ask_to_link() -> AliceResponse:
    return reply(
        f"Привет! Для начала привяжи аккаунт Huckleberry. "
        f"Зайди на {SETUP_URL}, получи код и скажи его мне.",
        end_session=False,
        buttons=[{"title": "Настроить yababy.oshev.me", "url": f"https://{SETUP_URL}", "hide": False}],
    )


async def _try_select_child(user: dict, cmd: str) -> AliceResponse:
    children = json.loads(user.get("children_json") or "[]")
    if not children:
        return reply("Нет данных о детях. Привяжите аккаунт заново на " + SETUP_URL, end_session=False)

    for child in children:
        voice_name = child.get("voice_name", child["name"]).lower()
        if voice_name in cmd:
            await db.update_user_child(user["alice_user_id"], child["uid"], voice_name)
            return reply(f"Отлично, слежу за {_cap(voice_name)}! {HELP_TEXT}")

    names = ", ".join(c.get("voice_name", c["name"]) for c in children)
    return reply(f"Не поняла имя. Скажите одно из: {names}", end_session=False)


def _is_pin(cmd: str) -> bool:
    clean = re.sub(r"\s+", "", cmd)
    return bool(re.fullmatch(r"\d{6}", clean))


async def _handle_link(alice_user_id: str, cmd: str) -> AliceResponse:
    pin = re.sub(r"\s+", "", cmd)
    data = await db.consume_pending_link(pin)
    if not data:
        return reply("Код неверный или истёк. Получите новый на " + SETUP_URL, end_session=False)

    children = data["children"]
    voice_name = children[0].get("voice_name", children[0]["name"])
    tz = data.get("timezone", "Europe/Moscow")
    if len(children) == 1:
        child = children[0]
        await db.upsert_user(
            alice_user_id=alice_user_id,
            hb_email=data["email"],
            hb_refresh_token=data["refresh_token"],
            timezone=tz,
            selected_child_uid=child["uid"],
            child_name=voice_name,
            children=children,
        )
        return reply(f"Готово! Аккаунт привязан, слежу за {_cap(voice_name)}. {HELP_TEXT}")

    await db.upsert_user(
        alice_user_id=alice_user_id,
        hb_email=data["email"],
        hb_refresh_token=data["refresh_token"],
        timezone=tz,
        children=children,
    )
    names = ", ".join(c.get("voice_name", c["name"]) for c in children)
    return reply(
        f"Аккаунт привязан! У вас несколько детей: {names}. Скажите имя ребёнка, за которым следить.",
        end_session=False,
    )


def _detect_intent(body: AliceRequestBody) -> str:
    intents = body.request.nlu.intents
    if intents:
        for name in intents:
            return name

    return _keyword_intent(body.command)


_KEYWORD_PATTERNS: list[tuple[str, str]] = [
    # sleep
    (r"уснул|уснула|заснул|заснула|спит|засыпает|укладываем|укладываю|лёг спать|легла спать|баиньки", "sleep.start"),
    (r"проснул(ся|ась)|встал|встала|не спит|подъём", "sleep.end"),
    # diaper (both must be before individual)
    (r"попис\w*.*покак\w*|покак\w*.*попис\w*", "diaper.both"),
    (r"покакал|покакала|накакал|накакала", "diaper.poo"),
    (r"пописал|пописала|написал|написала", "diaper.pee"),
    # bottle
    (r"\d+\s*(мл|миллилитр)|бутылоч", "feed.bottle"),
    # breast start
    (r"кушает|кормим|кормлю|ест\s+грудь|ест\s+(лев|прав)|кушает\s+(лев|прав)|кормим\s+(лев|прав)|кормлю\s+(лев|прав)|начал\w*\s+(есть|кушать|кормить)|сосёт|сосет", "feed.breast.start"),
    # breast end
    (r"поел|поела|покушал|покушала|наел(ся|ась)|накушал(ся|ась)|закончил\w*\s+(кормить|есть|кушать)|доел|доела|всё\s*съел|наелся", "feed.breast.end"),
    # status
    (r"когда\s+(ел|кушал|кормили|последний раз ел|последний раз кушал)", "status.feed"),
    (r"сколько не спит|когда проснул|когда спал|давно не спит", "status.sleep"),
    (r"когда\s+(какал|пописал|менял\w*\s+(подгузник|памперс)|(подгузник|памперс)\s+менял\w*|последний (подгузник|памперс))|когда (подгузник|памперс)|последний (подгузник|памперс)", "status.diaper"),
    (r"статус|как дела|что нового|как обстоят дела|расскажи", "status"),
    # help
    (r"помощь|помоги|что умеешь|что ты можешь|что ты умеешь", "help"),
]


def _keyword_intent(cmd: str) -> str:
    for pattern, intent in _KEYWORD_PATTERNS:
        if re.search(pattern, cmd):
            return intent
    return "unknown"


def _extract_side(cmd: str) -> str | None:
    if re.search(r"прав", cmd):
        return "right"
    if re.search(r"лев", cmd):
        return "left"
    return None


def _extract_ml(cmd: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*мл", cmd)
    if m:
        return float(m.group(1).replace(",", "."))
    m = re.search(r"(\d+(?:[.,]\d+)?)", cmd)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


async def _dispatch(intent: str, body: AliceRequestBody, user: dict) -> AliceResponse:
    match intent:
        case "sleep.start":
            return reply(await hb.start_sleep(user))
        case "sleep.end":
            return reply(await hb.complete_sleep(user))
        case "diaper.pee":
            return reply(await hb.log_diaper(user, mode="pee"))
        case "diaper.poo":
            return reply(await hb.log_diaper(user, mode="poo"))
        case "diaper.both":
            return reply(await hb.log_diaper(user, mode="both"))
        case "feed.bottle":
            amount = body.slot_value("feed.bottle", "amount")
            if amount is None:
                amount = _extract_ml(body.command)
            if amount is None:
                return reply("Сколько миллилитров? Скажи, например: выпил 60 мл.", end_session=False)
            return reply(await hb.log_bottle(user, amount=float(amount)))
        case "feed.breast.start":
            side = body.slot_value("feed.breast.start", "side") or _extract_side(body.command)
            return reply(await hb.start_feeding(user, side=side or "left"))
        case "feed.breast.end":
            return reply(await hb.complete_feeding(user))
        case "status":
            return reply(await hb.get_status(user, scope="full"))
        case "status.sleep":
            return reply(await hb.get_status(user, scope="sleep"))
        case "status.feed":
            return reply(await hb.get_status(user, scope="feed"))
        case "status.diaper":
            return reply(await hb.get_status(user, scope="diaper"))
        case "help" | "YANDEX.HELP":
            return reply(HELP_TEXT)
        case _:
            return reply("Не понял. " + HELP_TEXT, end_session=False)
