from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class AliceSession(BaseModel):
    session_id: str
    message_id: int
    skill_id: str = ""
    new: bool = False
    user_id: str = ""
    user: dict[str, str] = Field(default_factory=dict)
    application: dict[str, str] = Field(default_factory=dict)


class SlotValue(BaseModel):
    type: str
    value: Any


class IntentData(BaseModel):
    slots: dict[str, SlotValue] = Field(default_factory=dict)


class NLU(BaseModel):
    tokens: list[str] = Field(default_factory=list)
    entities: list[dict] = Field(default_factory=list)
    intents: dict[str, IntentData] = Field(default_factory=dict)


class AliceRequest(BaseModel):
    command: str = ""
    original_utterance: str = ""
    nlu: NLU = Field(default_factory=NLU)
    type: str = "SimpleUtterance"


class AliceRequestBody(BaseModel):
    meta: dict = Field(default_factory=dict)
    session: AliceSession
    request: AliceRequest
    version: str = "1.0"

    @property
    def alice_user_id(self) -> str:
        return self.session.user.get("user_id", "") or self.session.user_id

    @property
    def command(self) -> str:
        return self.request.command.strip().lower()

    def intent(self, name: str) -> IntentData | None:
        return self.request.nlu.intents.get(name)

    def slot_value(self, intent_name: str, slot_name: str) -> Any | None:
        intent = self.intent(intent_name)
        if intent and slot_name in intent.slots:
            return intent.slots[slot_name].value
        return None


class Response(BaseModel):
    text: str
    tts: Optional[str] = None
    end_session: bool = False
    buttons: list[dict] = Field(default_factory=list)


class AliceResponse(BaseModel):
    response: Response
    version: str = "1.0"


def reply(text: str, tts: str | None = None, end_session: bool = False, buttons: list[dict] | None = None) -> AliceResponse:
    return AliceResponse(
        response=Response(text=text, tts=tts, end_session=end_session, buttons=buttons or [])
    )
