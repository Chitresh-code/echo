"""A user's usage over a range of dates, summed from the ledger."""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from apps.agents.repositories import agents
from apps.credentials.repositories import credentials
from apps.usage.models.usage import Day, Prices, Share, Totals, UsageReport
from apps.usage.repositories import usage as ledger
from apps.usage.services import pricing
from core.errors import AppError

# A year and a day, so a leap year's full range fits. Longer ranges would only make a slower page.
MAX_DAYS = 366
TOKENS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise AppError(400, "usage_timezone_invalid", "That time zone is not known. Use an IANA name such as Europe/London.") from None


def check_range(start: date, end: date) -> None:
    if end < start:
        raise AppError(400, "usage_range_invalid", "The end date is before the start date.")
    if (end - start).days + 1 > MAX_DAYS:
        raise AppError(400, "usage_range_invalid", f"Pick at most {MAX_DAYS} days.")


def _tokens(row: dict) -> int:
    return sum(row[k] for k in TOKENS)


def _shares(rows: list[dict], key, names: dict[str, str], provider=None) -> list[Share]:
    groups: dict[str, dict] = defaultdict(lambda: {"cost_micros": 0, "tokens": 0, "turns": set(), "unpriced_tokens": 0, "provider": None})
    for row in rows:
        group = groups[key(row)]
        group["tokens"] += _tokens(row)
        group["turns"].add(row["turn_id"])
        if row["cost_micros"] is None:
            group["unpriced_tokens"] += _tokens(row)
        else:
            group["cost_micros"] += row["cost_micros"]
        if provider:
            group["provider"] = provider(row)
    shares = [
        Share(id=id_, name=names.get(id_), provider=g["provider"], cost_micros=g["cost_micros"], tokens=g["tokens"], turns=len(g["turns"]), unpriced_tokens=g["unpriced_tokens"])
        for id_, g in groups.items()
    ]
    return sorted(shares, key=lambda s: (-s.cost_micros, -s.tokens, s.id))


async def report(db: AsyncSession, user_id: str, start: date, end: date, tz: str) -> UsageReport:
    check_range(start, end)
    where = zone(tz)
    lo = datetime.combine(start, time(), where).astimezone(UTC)
    hi = datetime.combine(end + timedelta(days=1), time(), where).astimezone(UTC)
    rows = await ledger.rows_for(db, user_id, lo, hi)

    by_day = {start + timedelta(days=i): [0, 0] for i in range((end - start).days + 1)}
    for row in rows:
        # SQLite keeps no zone; the ledger is written in UTC.
        at = row["at"] if row["at"].tzinfo else row["at"].replace(tzinfo=UTC)
        day = by_day.get(at.astimezone(where).date())
        if day is not None:
            day[0] += row["cost_micros"] or 0
            day[1] += _tokens(row)

    workspace_names = {a.id: a.name for a in await agents.list_for(db, user_id)}
    key_names = {c.id: c.label for c in await credentials.list_for(db, user_id)}
    model_id = lambda row: f"{row['provider']}/{row['model']}"  # noqa: E731
    models = _shares(rows, model_id, {model_id(r): r["model"] for r in rows}, provider=lambda row: row["provider"])
    priced = [r for r in rows if r["cost_micros"] is not None]
    source = pricing.source()
    return UsageReport(
        totals=Totals(
            cost_micros=sum(r["cost_micros"] for r in priced),
            **{k: sum(r[k] for r in rows) for k in TOKENS},
            turns=len({r["turn_id"] for r in rows}),
            unpriced_tokens=sum(_tokens(r) for r in rows if r["cost_micros"] is None),
        ),
        days=[Day(date=d, cost_micros=c, tokens=t) for d, (c, t) in by_day.items()],
        workspaces=_shares(rows, lambda r: r["agent_id"], workspace_names),
        models=models,
        # A key's id is kept even after the key is deleted; rows from before keys were recorded have none.
        keys=_shares([r for r in rows if r["credential_id"]], lambda r: r["credential_id"], key_names),
        prices=Prices(source=source["source"], fetched=date.fromisoformat(source["fetched"])),
        since=await ledger.first_at(db, user_id),
    )
