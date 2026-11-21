from http import HTTPStatus

GENERIC_MESSAGE = "Something went wrong. Quote the request id when reporting it."


def code_for(status_code: int) -> str:
    """The default machine readable code for a status, such as not_found."""
    try:
        return HTTPStatus(status_code).phrase.lower().replace(" ", "_").replace("-", "_")
    except ValueError:
        return "error"


class AppError(Exception):
    """A failure the caller may see: a stable `code` to branch on and a `message` that is safe to
    show. Anything else about the cause belongs in the log, not here."""

    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


def safe_message(exc: BaseException) -> str:
    """What a caller may be told about a caught exception. Only AppError messages are written for
    callers; any other exception's text can hold provider bodies, paths or keys."""
    return exc.message if isinstance(exc, AppError) else GENERIC_MESSAGE
