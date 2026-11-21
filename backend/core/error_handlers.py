"""Every failure goes out in one shape:

    {"success": false, "error": {"code", "message", "details"}, "meta": {"request_id"}}

`code` is stable for callers to branch on and `message` is safe to show."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.errors import GENERIC_MESSAGE, AppError, code_for
from core.request_id import HEADER, request_id

logger = logging.getLogger(__name__)


def _response(request: Request, status_code: int, code: str, message: str, details: dict | None, headers=None) -> JSONResponse:
    level = logging.ERROR if status_code >= 500 else logging.WARNING
    logger.log(level, "%s %s failed with %s %s: %s", request.method, request.url.path, status_code, code, message)
    body = {
        "success": False,
        "error": {"code": code, "message": message, "details": details},
        "meta": {"request_id": request_id(request)},
    }
    return JSONResponse(status_code=status_code, content=body, headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return _response(request, exc.status_code, code_for(exc.status_code), str(exc.detail), None, getattr(exc, "headers", None))

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return _response(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        # Field names and pydantic's message only, never the submitted input: it can hold file
        # contents or prompts.
        fields = [{"field": ".".join(str(p) for p in e.get("loc", ())), "message": e.get("msg", "")} for e in exc.errors()]
        return _response(request, 422, "validation_error", "The request is not valid.", {"errors": fields})

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception", exc_info=exc)
        response = _response(request, 500, "internal_error", GENERIC_MESSAGE, None)
        # This handler runs outside the request id middleware, so it adds the header itself.
        response.headers[HEADER] = request_id(request)
        return response
