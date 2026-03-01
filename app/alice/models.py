from typing import Optional

from pydantic import BaseModel


class Response(BaseModel):
    text: str
    tts: Optional[str] = None
    end_session: bool = False


class AliceResponse(BaseModel):
    response: Response
    version: str = "1.0"
