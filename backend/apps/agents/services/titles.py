"""Names for new workspaces: a provisional one cut from the first message, shown at once, and a
short title the side model writes from it, which replaces it when it comes back."""

import asyncio
import logging
import re
import unicodedata

from strands import Agent
from strands.models import Model

from apps.agents.models.agent import DEFAULT_NAME

logger = logging.getLogger(__name__)

PROVISIONAL_CHARS = 60
TITLE_CHARS = 80
# A title is a nicety: past this the provisional name stays and nobody waits on it.
TITLE_TIMEOUT = 15
# The start of a request says what it is about; a pasted log after it only costs tokens.
PROMPT_CHARS = 4000
SYSTEM_PROMPT = (
    "You name conversations. Write a title of 2 to 6 words for the user's request, in the language of the request. "
    "Reply with the title only: no quotes, no punctuation at the end, and do not answer the request."
)

_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_MARKERS = re.compile(r"```\w*|[*_`#>~|]|^\s*(?:[-+]|\d+[.)])\s+", re.MULTILINE)
_LABEL = re.compile(r"^\s*title\s*:\s*", re.IGNORECASE)


def _plain(text: str) -> str:
    """Control characters and line breaks become spaces, and runs of whitespace one space."""
    text = "".join(" " if unicodedata.category(ch).startswith("C") else ch for ch in text)
    return " ".join(text.split())


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    # At a word when there is one in reach, so a name never ends mid-word.
    if text[limit - 1] != " " and " " in head[limit // 2 :]:
        head = head[: head.rindex(" ")]
    return head.rstrip(" ,.;:-") + "…"


def provisional(prompt: str) -> str:
    text = _plain(_MARKERS.sub(" ", _LINK.sub(r"\1", prompt)))
    return _cut(text, PROVISIONAL_CHARS) or DEFAULT_NAME


def clean(reply: str) -> str | None:
    """The model's title as one plain line, or None when nothing usable is left. It is shown as
    text, but it is still model output, so nothing in it is trusted."""
    line = next((l for l in reply.splitlines() if l.strip()), "")
    text = _plain(_MARKERS.sub("", _LABEL.sub("", line)))
    text = text.strip("\"'“”‘’«» ").rstrip(".!:;,")
    return _cut(text, TITLE_CHARS) or None


async def generate(side_model: Model, prompt: str) -> str | None:
    """A title for the request, or None if the model fails, is slow or says nothing usable."""
    try:
        async with asyncio.timeout(TITLE_TIMEOUT):
            agent = Agent(model=side_model, system_prompt=SYSTEM_PROMPT, tools=[], callback_handler=None)
            result = await agent.invoke_async(prompt[:PROMPT_CHARS])
        return clean(str(result))
    except Exception as e:
        # Only the kind of error: the prompt and the provider's text can carry the user's message.
        logger.warning("Could not title a workspace: %s", type(e).__name__)
        return None
