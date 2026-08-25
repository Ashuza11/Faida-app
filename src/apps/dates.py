"""Business-local date helpers shared by web and automated transactions."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


BUSINESS_TIMEZONE = ZoneInfo("Africa/Lubumbashi")


def business_local_date(moment: datetime | None = None) -> date:
    """Return the ledger date in Faida's configured business timezone."""
    moment = moment or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(BUSINESS_TIMEZONE).date()
