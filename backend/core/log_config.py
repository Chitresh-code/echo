"""One logging setup for the process: every line carries the id of the request it was written in,
and provider keys are masked even when a library logs one by mistake."""

import logging
import re
import sys

from core import request_id

_SECRETS = [
    (re.compile(r"(?i)(bearer\s+)[^\s\"',]+"), r"\1***"),
    # Provider key shapes: Anthropic and OpenAI style sk- keys, Google AIza keys.
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{8})[A-Za-z0-9_-]+"), r"\1***"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"), "AIza***"),
    (re.compile(r"(?i)\b(api[_-]?key|x-api-key|password|secret)(\W{1,4})[^\s\"'&,}]+"), r"\1\2***"),
]


def mask(text: str) -> str:
    for pattern, repl in _SECRETS:
        text = pattern.sub(repl, text)
    return text


class _Formatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.request_id = request_id.current() or "-"
        return mask(super().format(record))


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # uvicorn's own access log would duplicate the access line written with the request id.
    logging.getLogger("uvicorn.access").disabled = True
