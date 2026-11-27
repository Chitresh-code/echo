from datetime import date

from pydantic import BaseModel

from core.db import UtcDateTime

# Money is in millionths of a US dollar (micros), as integers, so totals add up exactly. Every cost
# is an estimate from list prices; the provider's bill is the truth.


class Totals(BaseModel):
    cost_micros: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    turns: int
    # Tokens of calls with no known price, left out of cost_micros.
    unpriced_tokens: int


class Day(BaseModel):
    date: date
    cost_micros: int
    tokens: int


class Share(BaseModel):
    """One workspace, model or key's part of the period."""

    id: str
    # The workspace name or key label as it is now, or null when it has been deleted. For a
    # model, the model id.
    name: str | None
    # For a model, its provider; otherwise null.
    provider: str | None = None
    cost_micros: int
    tokens: int
    turns: int
    unpriced_tokens: int


class Prices(BaseModel):
    # The price list the costs were estimated from, and the day it was copied.
    source: str
    fetched: date


class UsageReport(BaseModel):
    totals: Totals
    # Every date of the range, in the asked time zone, oldest first; days without use are zero.
    days: list[Day]
    workspaces: list[Share]
    models: list[Share]
    keys: list[Share]
    prices: Prices
    # When your usage was first counted, or null if it never was. Turns before it are not counted.
    since: UtcDateTime | None
