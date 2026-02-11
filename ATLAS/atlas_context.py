"""
Strategic Context Engine
Adds peer and sentiment context to single-stock event evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import re

try:
    from atlas_financial import FinancialDataService, EarningsReport
except Exception:  # Avoid hard dependency at import time
    FinancialDataService = None
    EarningsReport = None


class SectorTrend(Enum):
    ACCUMULATION = "ACCUMULATION"
    DISTRIBUTION = "DISTRIBUTION"
    NEUTRAL = "NEUTRAL"


class SentimentRegime(Enum):
    FEAR = "FEAR"
    GREED = "GREED"
    APATHY = "APATHY"


@dataclass
class ContextScore:
    peer_alignment: float  # -1.0 to 1.0
    sector_trend: SectorTrend
    sentiment_regime: SentimentRegime
    final_confidence_modifier: float


class CompetitorMatrix:
    """
    Analyze sector peers to detect sympathy moves and sector-wide weakness/strength.
    """

    def __init__(self, financial: Optional[FinancialDataService] = None):
        self.financial = financial
        self.peer_map: Dict[str, List[str]] = {
            "PEP": ["KO", "KDP", "MNST"],
            "KO": ["PEP", "KDP", "MNST"],
            "AAPL": ["MSFT", "GOOGL", "AMZN"],
            "MSFT": ["AAPL", "GOOGL", "AMZN"],
            "NVDA": ["AMD", "AVGO", "INTC"],
            "TSLA": ["GM", "F", "RIVN"],
            "JPM": ["BAC", "C", "WFC"],
            "META": ["GOOGL", "SNAP", "PINS"],
            "AMZN": ["WMT", "TGT", "COST"],
            "UNH": ["CVS", "CI", "HUM"],
        }
        self.sector_etf_map: Dict[str, str] = {
            "Consumer Staples": "XLP",
            "Technology": "XLK",
            "Health Care": "XLV",
            "Financials": "XLF",
            "Energy": "XLE",
            "Utilities": "XLU",
            "Industrials": "XLI",
            "Materials": "XLB",
            "Real Estate": "XLRE",
            "Communication Services": "XLC",
            "Consumer Discretionary": "XLY",
        }

    def _get_peers(self, symbol: str, sector: Optional[str]) -> List[str]:
        peers = self.peer_map.get(symbol, [])
        if peers:
            return peers[:3]
        return []

    async def get_peer_performance(self, symbol: str, sector: Optional[str]) -> Tuple[float, List[str]]:
        """
        Fetch top 3 competitors and compute sympathy correlation (0-1).
        Returns (sympathy_correlation, peer_symbols_used).
        """
        peers = self._get_peers(symbol, sector)
        if not peers or not self.financial or not hasattr(self.financial, "yahoo"):
            return 0.5, peers

        # Get current symbol performance from Yahoo
        sym_quote = await self.financial.yahoo.get_quote(symbol)
        sym_change = None
        if sym_quote:
            sym_change = sym_quote.get("regularMarketChangePercent")
        if sym_change is None:
            return 0.5, peers

        aligned = 0
        checked = 0
        for peer in peers:
            quote = await self.financial.yahoo.get_quote(peer)
            if not quote:
                continue
            peer_change = quote.get("regularMarketChangePercent")
            if peer_change is None:
                continue
            checked += 1
            if (peer_change >= 0 and sym_change >= 0) or (peer_change < 0 and sym_change < 0):
                aligned += 1

        if checked == 0:
            return 0.5, peers

        sympathy = aligned / checked
        return sympathy, peers

    async def calculate_sector_velocity(self, sector_etf: Optional[str]) -> SectorTrend:
        """
        Determine if sector is rotating In or Out using ETF price change.
        """
        if not sector_etf or not self.financial or not hasattr(self.financial, "yahoo"):
            return SectorTrend.NEUTRAL

        quote = await self.financial.yahoo.get_quote(sector_etf)
        if not quote:
            return SectorTrend.NEUTRAL

        change_pct = quote.get("regularMarketChangePercent")
        if change_pct is None:
            return SectorTrend.NEUTRAL

        if change_pct >= 0.5:
            return SectorTrend.ACCUMULATION
        if change_pct <= -0.5:
            return SectorTrend.DISTRIBUTION
        return SectorTrend.NEUTRAL

    def sector_to_etf(self, sector: Optional[str]) -> Optional[str]:
        if not sector:
            return None
        return self.sector_etf_map.get(sector)


class SentimentBacktest:
    """
    Compare current news sentiment against sentiment during previous earnings events.
    """

    POSITIVE = ["beat", "upgrade", "growth", "strong", "record", "raise", "outperform", "surge"]
    NEGATIVE = ["miss", "downgrade", "weak", "cut", "lawsuit", "probe", "decline", "warning"]

    def __init__(self, financial: Optional[FinancialDataService] = None):
        self.financial = financial

    def _score_sentiment(self, text: str) -> float:
        if not text:
            return 0.0
        t = text.lower()
        pos = sum(1 for w in self.POSITIVE if w in t)
        neg = sum(1 for w in self.NEGATIVE if w in t)
        if pos == 0 and neg == 0:
            return 0.0
        score = (pos - neg) / max(1, pos + neg)
        return max(-1.0, min(1.0, score))

    async def correlate_sentiment_outcome(
        self,
        symbol: str,
        historical_earnings: Optional[List[object]]
    ) -> str:
        """
        Determine if stock tends to move with sentiment (Momentum) or against it (Contrarian).
        Returns: "momentum", "contrarian", or "neutral".
        """
        if not historical_earnings or not self.financial:
            return "neutral"

        # Without historical news snapshots, use a simplified heuristic:
        # If average move is large and inconsistent, treat as contrarian risk.
        moves = [e.stock_move_pct for e in historical_earnings if getattr(e, "stock_move_pct", None) is not None]
        if not moves:
            return "neutral"
        avg_move = sum(abs(m) for m in moves) / len(moves)
        if avg_move >= 5.0:
            return "contrarian"
        return "momentum"

    async def get_current_context_score(self, symbol: str, regime: str) -> float:
        """
        Return a ContextAdjustmentFactor (-0.2 to +0.2).
        """
        if not self.financial:
            return 0.0
        news = await self.financial.check_news(symbol)
        sentiment = self._score_sentiment(news.get("news_summary", ""))
        if regime == "contrarian":
            sentiment *= -1
        # Scale to [-0.2, 0.2]
        return max(-0.2, min(0.2, sentiment * 0.2))


class StrategicContextEngine:
    """
    Orchestrates competitor and sentiment context into a single score.
    """

    def __init__(self, financial: Optional[FinancialDataService] = None):
        self.financial = financial
        self.competitors = CompetitorMatrix(financial)
        self.sentiment = SentimentBacktest(financial)

    async def analyze(
        self,
        symbol: str,
        sector: Optional[str],
        historical_earnings: Optional[List[object]]
    ) -> ContextScore:
        sympathy, _ = await self.competitors.get_peer_performance(symbol, sector)
        sector_etf = self.competitors.sector_to_etf(sector)
        sector_trend = await self.competitors.calculate_sector_velocity(sector_etf)

        regime = await self.sentiment.correlate_sentiment_outcome(symbol, historical_earnings)
        sentiment_adj = await self.sentiment.get_current_context_score(symbol, regime)

        # Convert sympathy (0-1) to alignment (-1 to 1), center at 0.5
        peer_alignment = max(-1.0, min(1.0, (sympathy - 0.5) * 2))

        if sentiment_adj >= 0.1:
            sentiment_regime = SentimentRegime.GREED
        elif sentiment_adj <= -0.1:
            sentiment_regime = SentimentRegime.FEAR
        else:
            sentiment_regime = SentimentRegime.APATHY

        # Final confidence modifier
        modifier = 0.0
        if sector_trend == SectorTrend.DISTRIBUTION:
            modifier -= 0.05
        if sector_trend == SectorTrend.ACCUMULATION:
            modifier += 0.05
        modifier += sentiment_adj

        return ContextScore(
            peer_alignment=peer_alignment,
            sector_trend=sector_trend,
            sentiment_regime=sentiment_regime,
            final_confidence_modifier=max(-0.2, min(0.2, modifier))
        )

    def analyze_sync(
        self,
        symbol: str,
        sector: Optional[str],
        historical_earnings: Optional[List[object]]
    ) -> ContextScore:
        """
        Synchronous wrapper for analyze. Falls back to neutral if called inside
        an already-running event loop.
        """
        try:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # Avoid nested event loop calls
                return ContextScore(
                    peer_alignment=0.0,
                    sector_trend=SectorTrend.NEUTRAL,
                    sentiment_regime=SentimentRegime.APATHY,
                    final_confidence_modifier=0.0
                )

            return asyncio.run(self.analyze(symbol, sector, historical_earnings))
        except Exception:
            return ContextScore(
                peer_alignment=0.0,
                sector_trend=SectorTrend.NEUTRAL,
                sentiment_regime=SentimentRegime.APATHY,
                final_confidence_modifier=0.0
            )
