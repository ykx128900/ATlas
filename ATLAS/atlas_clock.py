"""
ATLAS Market Clock
Utility for scheduling in US/Eastern time with trading calendar support.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, time
from typing import Optional, Dict, List

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover (Python <3.9)
    ZoneInfo = None


@dataclass
class MarketClock:
    """
    Time helper that normalizes scheduling to a specific timezone.
    Uses Alpaca calendar data when available.
    """
    alpaca: object
    timezone: str = "America/New_York"

    def _tz(self):
        if ZoneInfo is None:
            return None
        return ZoneInfo(self.timezone)

    def now(self) -> datetime:
        tz = self._tz()
        if tz:
            return datetime.now(tz)
        return datetime.now()

    def today(self) -> date:
        return self.now().date()

    def parse_hhmm(self, value: str) -> time:
        return datetime.strptime(value, "%H:%M").time()

    def is_within_window(self, now_t: time, start: time, end: time) -> bool:
        return start <= now_t <= end

    async def get_calendar(self, start: Optional[date] = None, end: Optional[date] = None) -> List[Dict]:
        if hasattr(self.alpaca, "get_calendar"):
            return await self.alpaca.get_calendar(start=start, end=end)
        return []

    async def is_trading_day(self, day: date) -> bool:
        cal = await self.get_calendar(start=day, end=day)
        return bool(cal)

    async def is_market_open(self) -> bool:
        if hasattr(self.alpaca, "is_market_open"):
            return await self.alpaca.is_market_open()
        return False
