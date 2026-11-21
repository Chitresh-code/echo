"""Every JSON success goes out in one shape, matching the error shape:

    {"success": true, "data": <what the endpoint returned>, "meta": {"request_id"}}

Streams and any response an endpoint builds itself are never wrapped."""

from typing import Any

from fastapi.responses import JSONResponse

from core import request_id


def envelope(data: Any) -> dict:
    return {"success": True, "data": data, "meta": {"request_id": request_id.current()}}


class EnvelopeJSONResponse(JSONResponse):
    """The app's default response class, so it wraps exactly what FastAPI serialised from an
    endpoint's return value, after `response_model` was applied."""

    def render(self, content: Any) -> bytes:
        return super().render(envelope(content))
