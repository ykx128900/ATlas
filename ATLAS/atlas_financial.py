"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                      ATLAS FINANCIAL DATA MODULE                              ║
║            Perplexity Finance + Yahoo Finance + Google Finance                ║
╚══════════════════════════════════════════════════════════════════════════════╝

This module provides ATLAS with comprehensive financial data:
- Primary: Perplexity Finance (real-time, comprehensive)
- Backup 1: Yahoo Finance (historical, fundamental)
- Backup 2: Google Finance (real-time quotes)

Author: ATLAS Development Team
Version: 1.0.0 - Production Ready
"""

import asyncio
import aiohttp
import json
import logging
import re
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ATLAS.Financial")

# ══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class EarningsReport:
    """Single earnings report data"""
    symbol: str
    date: date
    quarter: str  # e.g., "Q4 2024"
    fiscal_year: int
    
    # Results
    revenue: float
    revenue_estimate: float
    revenue_surprise_pct: float
    
    eps: float
    eps_estimate: float
    eps_surprise_pct: float
    
    # Additional metrics
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    
    # Guidance
    guidance_revenue_low: Optional[float] = None
    guidance_revenue_high: Optional[float] = None
    guidance_eps_low: Optional[float] = None
    guidance_eps_high: Optional[float] = None
    
    # Market reaction
    stock_move_pct: Optional[float] = None  # Next-day move

@dataclass
class CompanyFinancials:
    """Comprehensive company financial profile"""
    symbol: str
    name: str
    sector: str
    industry: str
    market_cap: float
    
    # Valuation
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    price_to_book: Optional[float] = None
    price_to_sales: Optional[float] = None
    
    # Profitability
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    roe: Optional[float] = None  # Return on Equity
    roa: Optional[float] = None  # Return on Assets
    
    # Growth
    revenue_growth_yoy: Optional[float] = None
    earnings_growth_yoy: Optional[float] = None
    
    # Balance Sheet
    total_debt: Optional[float] = None
    total_cash: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    
    # Dividend
    dividend_yield: Optional[float] = None
    payout_ratio: Optional[float] = None
    
    # Historical earnings
    earnings_history: List[EarningsReport] = field(default_factory=list)
    
    # Analyst data
    analyst_rating: Optional[str] = None  # Buy/Hold/Sell
    price_target_low: Optional[float] = None
    price_target_mean: Optional[float] = None
    price_target_high: Optional[float] = None
    
    # ATLAS-specific metrics
    earnings_predictability_score: float = 0.0  # 0-1 score
    guidance_reliability_score: float = 0.0  # 0-1 score
    historical_move_avg: float = 0.0  # Average earnings move %

@dataclass
class UpcomingEarnings:
    """Upcoming earnings event"""
    symbol: str
    company_name: str
    earnings_date: date
    earnings_time: str  # "BMO" (Before Market Open) or "AMC" (After Market Close)
    
    # Estimates
    eps_estimate: Optional[float] = None
    revenue_estimate: Optional[float] = None
    
    # Historical context
    last_quarter_surprise_pct: Optional[float] = None
    avg_move_pct: Optional[float] = None
    beat_rate: Optional[float] = None  # % of times beat estimates
    
    # Current IV context
    current_iv: Optional[float] = None
    historical_iv: Optional[float] = None  # Typical IV before earnings
    
    # ATLAS score
    tradability_score: float = 0.0  # 0-100

    # Data quality metadata
    source: str = "unknown"  # perplexity|yahoo|local
    confidence: str = "medium"  # low|medium|high
    last_verified: Optional[date] = None

@dataclass
class MacroEvent:
    """Economic/macro event"""
    event_type: str  # FOMC, CPI, NFP, GDP, PCE, etc.
    event_date: date
    event_time: str
    description: str
    
    # Expectations
    prior_value: Optional[float] = None
    consensus_estimate: Optional[float] = None
    
    # Market impact
    historical_spy_move: Optional[float] = None
    historical_vix_move: Optional[float] = None
    
    importance: str = "medium"  # low, medium, high


# ══════════════════════════════════════════════════════════════════════════════
# PERPLEXITY FINANCE CLIENT
# ══════════════════════════════════════════════════════════════════════════════

class PerplexityFinanceClient:
    """
    Primary financial data source using Perplexity's sonar model.
    
    Perplexity Finance provides:
    - Real-time earnings data
    - Comprehensive financial analysis
    - Historical earnings patterns
    - Upcoming earnings calendar
    - Macro event tracking
    """
    
    API_URL = "https://api.perplexity.ai/chat/completions"
    MODEL = "llama-3.1-sonar-large-128k-online"  # Online model for real-time data
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, Tuple[datetime, str]] = {}
        self.cache_ttl_seconds: int = 600
        
        logger.info("PerplexityFinanceClient initialized")
    
    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def _query(
        self,
        query: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1
    ) -> str:
        """Query Perplexity API"""
        cache_key = f"{system_prompt or ''}||{query}"
        cached = self._cache.get(cache_key)
        if cached:
            ts, resp = cached
            if (datetime.now() - ts).total_seconds() <= self.cache_ttl_seconds:
                return resp

        session = await self._get_session()
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": query})
        
        payload = {
            "model": self.MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 4000
        }
        
        try:
            async with session.post(
                self.API_URL,
                headers=self.headers,
                json=payload
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    self._cache[cache_key] = (datetime.now(), content)
                    return content
                else:
                    error = await response.text()
                    logger.error(f"Perplexity API error {response.status}: {error}")
                    return ""
        except Exception as e:
            logger.error(f"Perplexity query failed: {e}")
            return ""
    
    async def get_upcoming_earnings(
        self,
        days_ahead: int = 7,
        sectors: Optional[List[str]] = None
    ) -> List[UpcomingEarnings]:
        """Get upcoming earnings for the next N days"""
        
        system_prompt = """You are a financial data assistant. Provide accurate, structured data about upcoming earnings.
        
        Format your response as JSON with this structure:
        {
            "earnings": [
                {
                    "symbol": "AAPL",
                    "company_name": "Apple Inc.",
                    "earnings_date": "2025-01-30",
                    "earnings_time": "AMC",
                    "eps_estimate": 2.35,
                    "revenue_estimate": 124500000000,
                    "beat_rate": 0.875
                }
            ]
        }
        
        Only include verified upcoming earnings. If uncertain about a date, note it."""
        
        sector_filter = f" Focus on these sectors: {', '.join(sectors)}." if sectors else ""
        
        query = f"""What are the confirmed earnings reports scheduled for the next {days_ahead} days from today?{sector_filter}

For each company, provide:
- Stock symbol
- Company name
- Exact earnings date
- Timing (BMO = Before Market Open, AMC = After Market Close)
- EPS estimate (consensus)
- Revenue estimate
- Historical beat rate (percentage of times they beat estimates)

Only include earnings with confirmed dates. Today is {date.today().isoformat()}."""
        
        response = await self._query(query, system_prompt)
        
        return self._parse_earnings_response(response)
    
    def _parse_earnings_response(self, response: str) -> List[UpcomingEarnings]:
        """Parse Perplexity response into UpcomingEarnings objects"""
        earnings = []
        
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group())
                
                for item in data.get("earnings", []):
                    try:
                        earnings.append(UpcomingEarnings(
                            symbol=item.get("symbol", ""),
                            company_name=item.get("company_name", ""),
                            earnings_date=date.fromisoformat(item.get("earnings_date", "")),
                            earnings_time=item.get("earnings_time", "AMC"),
                            eps_estimate=item.get("eps_estimate"),
                            revenue_estimate=item.get("revenue_estimate"),
                            beat_rate=item.get("beat_rate"),
                            source="perplexity",
                            confidence="medium",
                            last_verified=date.today()
                        ))
                    except Exception as e:
                        logger.warning(f"Failed to parse earnings item: {e}")
                        continue
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON from Perplexity response")
            # Try line-by-line parsing as fallback
            pass
        
        return earnings
    
    async def get_earnings_history(
        self,
        symbol: str,
        quarters: int = 8
    ) -> List[EarningsReport]:
        """Get historical earnings data for a symbol"""
        
        system_prompt = """You are a financial data assistant. Provide accurate historical earnings data.
        
        Format your response as JSON:
        {
            "earnings": [
                {
                    "date": "2024-10-31",
                    "quarter": "Q4 2024",
                    "fiscal_year": 2024,
                    "revenue": 94930000000,
                    "revenue_estimate": 94500000000,
                    "revenue_surprise_pct": 0.45,
                    "eps": 1.64,
                    "eps_estimate": 1.60,
                    "eps_surprise_pct": 2.5,
                    "stock_move_pct": -2.3
                }
            ]
        }"""
        
        query = f"""Provide the last {quarters} quarters of earnings history for {symbol}.

For each quarter include:
- Exact earnings date
- Quarter (Q1, Q2, Q3, Q4) and fiscal year
- Actual revenue vs estimate and surprise %
- Actual EPS vs estimate and surprise %
- Stock price move on earnings day (next trading day for AMC)

Be precise with the numbers. Use the most recent data available."""
        
        response = await self._query(query, system_prompt)
        
        return self._parse_earnings_history(response, symbol)
    
    def _parse_earnings_history(self, response: str, symbol: str) -> List[EarningsReport]:
        """Parse earnings history response"""
        history = []
        
        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group())
                
                for item in data.get("earnings", []):
                    try:
                        history.append(EarningsReport(
                            symbol=symbol,
                            date=date.fromisoformat(item.get("date", "")),
                            quarter=item.get("quarter", ""),
                            fiscal_year=item.get("fiscal_year", 0),
                            revenue=item.get("revenue", 0),
                            revenue_estimate=item.get("revenue_estimate", 0),
                            revenue_surprise_pct=item.get("revenue_surprise_pct", 0),
                            eps=item.get("eps", 0),
                            eps_estimate=item.get("eps_estimate", 0),
                            eps_surprise_pct=item.get("eps_surprise_pct", 0),
                            stock_move_pct=item.get("stock_move_pct")
                        ))
                    except Exception as e:
                        logger.warning(f"Failed to parse earnings history item: {e}")
                        continue
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON from earnings history response")
        
        return history
    
    async def get_company_financials(self, symbol: str) -> Optional[CompanyFinancials]:
        """Get comprehensive financial profile for a company"""
        
        system_prompt = """You are a financial data assistant. Provide comprehensive company financial data.
        
        Format response as JSON:
        {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "market_cap": 3000000000000,
            "pe_ratio": 28.5,
            "forward_pe": 25.2,
            "peg_ratio": 2.1,
            "price_to_book": 45.2,
            "price_to_sales": 7.8,
            "gross_margin": 0.45,
            "operating_margin": 0.30,
            "net_margin": 0.25,
            "roe": 0.145,
            "revenue_growth_yoy": 0.05,
            "earnings_growth_yoy": 0.08,
            "total_debt": 110000000000,
            "total_cash": 65000000000,
            "debt_to_equity": 1.8,
            "current_ratio": 1.05,
            "dividend_yield": 0.005,
            "analyst_rating": "Buy",
            "price_target_mean": 225
        }"""
        
        query = f"""Provide comprehensive financial data for {symbol}.

Include:
1. Company basics (name, sector, industry, market cap)
2. Valuation metrics (P/E, Forward P/E, PEG, P/B, P/S)
3. Profitability metrics (gross margin, operating margin, net margin, ROE)
4. Growth metrics (revenue growth YoY, earnings growth YoY)
5. Balance sheet (total debt, total cash, debt/equity, current ratio)
6. Dividend info (yield, payout ratio)
7. Analyst consensus (rating, price targets)

Use the most current data available."""
        
        response = await self._query(query, system_prompt)
        
        return self._parse_company_financials(response, symbol)
    
    def _parse_company_financials(self, response: str, symbol: str) -> Optional[CompanyFinancials]:
        """Parse company financials response"""
        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group())
                
                return CompanyFinancials(
                    symbol=symbol,
                    name=data.get("name", symbol),
                    sector=data.get("sector", "Unknown"),
                    industry=data.get("industry", "Unknown"),
                    market_cap=data.get("market_cap", 0),
                    pe_ratio=data.get("pe_ratio"),
                    forward_pe=data.get("forward_pe"),
                    peg_ratio=data.get("peg_ratio"),
                    price_to_book=data.get("price_to_book"),
                    price_to_sales=data.get("price_to_sales"),
                    gross_margin=data.get("gross_margin"),
                    operating_margin=data.get("operating_margin"),
                    net_margin=data.get("net_margin"),
                    roe=data.get("roe"),
                    revenue_growth_yoy=data.get("revenue_growth_yoy"),
                    earnings_growth_yoy=data.get("earnings_growth_yoy"),
                    total_debt=data.get("total_debt"),
                    total_cash=data.get("total_cash"),
                    debt_to_equity=data.get("debt_to_equity"),
                    current_ratio=data.get("current_ratio"),
                    dividend_yield=data.get("dividend_yield"),
                    analyst_rating=data.get("analyst_rating"),
                    price_target_low=data.get("price_target_low"),
                    price_target_mean=data.get("price_target_mean"),
                    price_target_high=data.get("price_target_high")
                )
        except Exception as e:
            logger.error(f"Failed to parse company financials: {e}")
        
        return None
    
    async def get_macro_events(self, days_ahead: int = 14) -> List[MacroEvent]:
        """Get upcoming macro economic events"""
        
        system_prompt = """You are an economic calendar assistant. Provide accurate macro event data.
        
        Format as JSON:
        {
            "events": [
                {
                    "event_type": "FOMC",
                    "event_date": "2025-01-29",
                    "event_time": "14:00",
                    "description": "Federal Reserve Interest Rate Decision",
                    "prior_value": 5.5,
                    "consensus_estimate": 5.25,
                    "importance": "high"
                }
            ]
        }
        
        Include: FOMC, CPI, NFP, GDP, PCE, PPI, Retail Sales, Fed speeches"""
        
        query = f"""List all major US economic events for the next {days_ahead} days.

Include:
- FOMC meetings and rate decisions
- CPI (Consumer Price Index) releases
- NFP (Non-Farm Payrolls) reports
- GDP releases
- PCE (Personal Consumption Expenditures)
- PPI (Producer Price Index)
- Retail Sales
- Major Fed speeches

For each, provide:
- Event type
- Date and time (EST)
- Brief description
- Prior value (if applicable)
- Consensus estimate
- Importance level (low/medium/high)

Today is {date.today().isoformat()}."""
        
        response = await self._query(query, system_prompt)
        
        return self._parse_macro_events(response)
    
    def _parse_macro_events(self, response: str) -> List[MacroEvent]:
        """Parse macro events response"""
        events = []
        
        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group())
                
                for item in data.get("events", []):
                    try:
                        events.append(MacroEvent(
                            event_type=item.get("event_type", ""),
                            event_date=date.fromisoformat(item.get("event_date", "")),
                            event_time=item.get("event_time", ""),
                            description=item.get("description", ""),
                            prior_value=item.get("prior_value"),
                            consensus_estimate=item.get("consensus_estimate"),
                            importance=item.get("importance", "medium")
                        ))
                    except Exception as e:
                        logger.warning(f"Failed to parse macro event: {e}")
                        continue
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON from macro events response")
        
        return events
    
    async def check_breaking_news(self, symbol: str) -> Dict:
        """Check for breaking news that might affect a position"""
        
        query = f"""What is the latest breaking news for {symbol} in the past 24 hours?
        
        Focus on:
        - Earnings announcements or guidance changes
        - Product launches or recalls
        - Executive changes
        - Legal/regulatory issues
        - Analyst upgrades/downgrades
        - M&A activity
        - Any material news that could move the stock significantly
        
        Rate the overall sentiment: positive, negative, or neutral.
        Rate the potential stock impact: none, low, medium, high."""
        
        response = await self._query(query)
        
        return {
            "symbol": symbol,
            "news_summary": response,
            "timestamp": datetime.now().isoformat()
        }
    
    async def assess_earnings_tradability(self, symbol: str) -> Dict:
        """Assess how tradable an earnings event is for iron condors"""
        
        system_prompt = """You are an options trading analyst assessing earnings tradability for iron condors.
        
        Format response as JSON:
        {
            "symbol": "AAPL",
            "tradability_score": 75,
            "predictability_score": 80,
            "factors": {
                "historical_consistency": "high",
                "options_liquidity": "excellent",
                "typical_move_range": "1-3%",
                "guidance_reliability": "good",
                "binary_risk_factors": []
            },
            "recommendation": "Good candidate for iron condor",
            "warnings": [],
            "suggested_strategy": "Short straddle or iron condor with 1-sigma strikes"
        }"""
        
        query = f"""Assess {symbol} for earnings iron condor trading:

1. Historical earnings move patterns (last 8 quarters)
2. Consistency of moves (low variance = better)
3. Options liquidity and bid-ask spreads
4. Guidance reliability (does company give guidance?)
5. Binary risk factors (FDA decisions, lawsuits, etc.)
6. Sector characteristics (predictable vs volatile)
7. Current IV vs historical earnings IV

Give a tradability score (0-100) and detailed assessment."""
        
        response = await self._query(query, system_prompt)
        
        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
        except:
            pass
        
        return {
            "symbol": symbol,
            "raw_response": response
        }


# ══════════════════════════════════════════════════════════════════════════════
# YAHOO FINANCE CLIENT (Backup)
# ══════════════════════════════════════════════════════════════════════════════

class YahooFinanceClient:
    """
    Backup financial data source using Yahoo Finance.
    
    Uses the free Yahoo Finance API endpoints.
    """
    
    BASE_URL = "https://query1.finance.yahoo.com/v10/finance"
    QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
    
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        logger.info("YahooFinanceClient initialized")
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            self._session = aiohttp.ClientSession(headers=headers)
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def get_quote(self, symbol: str) -> Optional[Dict]:
        """Get real-time quote for a symbol"""
        session = await self._get_session()
        
        params = {
            "symbols": symbol,
            "fields": "regularMarketPrice,regularMarketChange,regularMarketChangePercent,regularMarketVolume,bid,ask,marketCap"
        }
        
        try:
            async with session.get(self.QUOTE_URL, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    result = data.get("quoteResponse", {}).get("result", [])
                    if result:
                        return result[0]
        except Exception as e:
            logger.error(f"Yahoo quote failed: {e}")
        
        return None
    
    async def get_key_statistics(self, symbol: str) -> Optional[Dict]:
        """Get key statistics for a symbol"""
        session = await self._get_session()
        
        url = f"{self.BASE_URL}/quoteSummary/{symbol}"
        params = {
            "modules": "defaultKeyStatistics,financialData,earnings"
        }
        
        try:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("quoteSummary", {}).get("result", [{}])[0]
        except Exception as e:
            logger.error(f"Yahoo key stats failed: {e}")
        
        return None
    
    async def get_earnings_dates(self, symbol: str) -> List[Dict]:
        """Get historical and upcoming earnings dates"""
        session = await self._get_session()
        
        url = f"{self.BASE_URL}/quoteSummary/{symbol}"
        params = {
            "modules": "calendarEvents,earningsHistory"
        }
        
        try:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    result = data.get("quoteSummary", {}).get("result", [{}])[0]
                    
                    earnings = []
                    
                    # Get upcoming earnings
                    calendar = result.get("calendarEvents", {}).get("earnings", {})
                    if calendar.get("earningsDate"):
                        for earn_date in calendar.get("earningsDate", []):
                            earnings.append({
                                "date": datetime.fromtimestamp(earn_date.get("raw", 0)).date().isoformat(),
                                "type": "upcoming",
                                "eps_estimate": calendar.get("earningsAverage", {}).get("raw"),
                                "revenue_estimate": calendar.get("revenueAverage", {}).get("raw")
                            })
                    
                    # Get historical earnings
                    history = result.get("earningsHistory", {}).get("history", [])
                    for hist in history:
                        earnings.append({
                            "date": hist.get("quarter", {}).get("fmt"),
                            "type": "historical",
                            "eps_actual": hist.get("epsActual", {}).get("raw"),
                            "eps_estimate": hist.get("epsEstimate", {}).get("raw"),
                            "surprise_pct": hist.get("surprisePercent", {}).get("raw")
                        })
                    
                    return earnings
        except Exception as e:
            logger.error(f"Yahoo earnings dates failed: {e}")
        
        return []
    
    async def get_financials(self, symbol: str) -> Optional[Dict]:
        """Get financial statements"""
        session = await self._get_session()
        
        url = f"{self.BASE_URL}/quoteSummary/{symbol}"
        params = {
            "modules": "incomeStatementHistory,balanceSheetHistory,cashflowStatementHistory"
        }
        
        try:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("quoteSummary", {}).get("result", [{}])[0]
        except Exception as e:
            logger.error(f"Yahoo financials failed: {e}")
        
        return None


# ══════════════════════════════════════════════════════════════════════════════
# GOOGLE FINANCE CLIENT (Backup)
# ══════════════════════════════════════════════════════════════════════════════

class GoogleFinanceClient:
    """
    Backup data source using Google Finance.
    
    Note: Google Finance doesn't have a public API, so we use web scraping
    for basic quote data as a last resort.
    """
    
    QUOTE_URL = "https://www.google.com/finance/quote"
    
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        logger.info("GoogleFinanceClient initialized (limited functionality)")
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            self._session = aiohttp.ClientSession(headers=headers)
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def get_quote(self, symbol: str, exchange: str = "NASDAQ") -> Optional[Dict]:
        """
        Get basic quote from Google Finance.
        
        Note: This is web scraping and may break if Google changes their page.
        Use as last resort only.
        """
        session = await self._get_session()
        
        url = f"{self.QUOTE_URL}/{symbol}:{exchange}"
        
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    html = await response.text()
                    
                    # Try to extract price from the page
                    # This is fragile and may need updates
                    price_match = re.search(r'data-last-price="([0-9.]+)"', html)
                    change_match = re.search(r'data-last-normal-market-change-percent="([0-9.-]+)"', html)
                    
                    if price_match:
                        return {
                            "symbol": symbol,
                            "price": float(price_match.group(1)),
                            "change_pct": float(change_match.group(1)) if change_match else None,
                            "source": "google_finance"
                        }
        except Exception as e:
            logger.error(f"Google Finance quote failed: {e}")
        
        return None


# ══════════════════════════════════════════════════════════════════════════════
# UNIFIED FINANCIAL DATA SERVICE
# ══════════════════════════════════════════════════════════════════════════════

class FinancialDataService:
    """
    Unified financial data service for ATLAS.
    
    Tries data sources in order:
    1. Perplexity Finance (primary)
    2. Yahoo Finance (backup)
    3. Google Finance (last resort)
    """
    
    def __init__(
        self,
        perplexity_api_key: Optional[str] = None,
        earnings_calendar_path: Optional[str] = None,
        macro_calendar_path: Optional[str] = None
    ):
        self.perplexity = PerplexityFinanceClient(perplexity_api_key) if perplexity_api_key else None
        self.yahoo = YahooFinanceClient()
        self.google = GoogleFinanceClient()
        self.earnings_calendar_path = earnings_calendar_path
        self.macro_calendar_path = macro_calendar_path
        self._yahoo_earnings_cache: Dict[str, Tuple[datetime, List[Dict]]] = {}
        
        logger.info("FinancialDataService initialized")
        if self.perplexity:
            logger.info("  Primary: Perplexity Finance ✓")
        else:
            logger.warning("  Primary: Perplexity Finance ✗ (no API key)")
        logger.info("  Backup 1: Yahoo Finance ✓")
        logger.info("  Backup 2: Google Finance ✓")
    
    async def close(self):
        """Close all client sessions"""
        if self.perplexity:
            await self.perplexity.close()
        await self.yahoo.close()
        await self.google.close()

    # ══════════════════════════════════════════════════════════════════════
    # VALIDATION & LOCAL DATA
    # ══════════════════════════════════════════════════════════════════════

    def _load_local_calendar(self, path: Optional[str]) -> Optional[Dict]:
        if not path:
            return None
        p = Path(path)
        if not p.exists():
            return None
        try:
            with p.open("r") as f:
                data = json.load(f)
            last_updated = data.get("last_updated")
            if last_updated:
                try:
                    updated_date = date.fromisoformat(last_updated)
                except Exception:
                    return None
                if (date.today() - updated_date).days > 7:
                    return None
            return data
        except Exception as e:
            logger.warning(f"Failed to load local calendar {path}: {e}")
            return None

    def _validate_upcoming_earnings(
        self,
        item: UpcomingEarnings,
        days_ahead: int
    ) -> Tuple[bool, List[str]]:
        errors = []
        if not item.symbol:
            errors.append("missing_symbol")
        if not item.earnings_date:
            errors.append("missing_date")
        else:
            if item.earnings_date < date.today():
                errors.append("date_in_past")
            if item.earnings_date > date.today() + timedelta(days=days_ahead):
                errors.append("date_out_of_window")
        if not item.earnings_time:
            errors.append("missing_time")
        else:
            time_upper = item.earnings_time.upper()
            if time_upper not in {"BMO", "AMC", "INTRADAY"}:
                if not re.match(r"^\d{2}:\d{2}$", item.earnings_time):
                    errors.append("bad_time_format")
        if item.eps_estimate is not None and abs(item.eps_estimate) > 1000:
            errors.append("eps_implausible")
        if item.revenue_estimate is not None and item.revenue_estimate < 0:
            errors.append("revenue_negative")
        if item.beat_rate is not None and not (0 <= item.beat_rate <= 1):
            errors.append("beat_rate_out_of_range")
        return (len(errors) == 0, errors)

    def _validate_macro_event(
        self,
        event: MacroEvent,
        days_ahead: int
    ) -> Tuple[bool, List[str]]:
        errors = []
        if not event.event_type:
            errors.append("missing_type")
        if not event.event_date:
            errors.append("missing_date")
        else:
            if event.event_date < date.today():
                errors.append("date_in_past")
            if event.event_date > date.today() + timedelta(days=days_ahead):
                errors.append("date_out_of_window")
        if not event.event_time:
            errors.append("missing_time")
        return (len(errors) == 0, errors)

    async def _get_yahoo_earnings_cached(self, symbol: str) -> List[Dict]:
        cached = self._yahoo_earnings_cache.get(symbol)
        if cached and (datetime.now() - cached[0]).total_seconds() < 3600:
            return cached[1]
        data = await self.yahoo.get_earnings_dates(symbol)
        self._yahoo_earnings_cache[symbol] = (datetime.now(), data)
        return data

    def _cross_validate_earnings(
        self,
        primary: UpcomingEarnings,
        yahoo_item: Optional[Dict]
    ) -> Tuple[str, List[str]]:
        """
        Compare primary (Perplexity/local) against Yahoo.
        Returns confidence and reasons.
        """
        reasons = []
        if not yahoo_item:
            return ("medium", ["no_yahoo_match"])

        yahoo_date_str = yahoo_item.get("date")
        yahoo_date = None
        try:
            yahoo_date = date.fromisoformat(yahoo_date_str)
        except Exception:
            reasons.append("yahoo_bad_date")

        if yahoo_date and primary.earnings_date and yahoo_date != primary.earnings_date:
            reasons.append("date_mismatch")

        # Compare estimates if both available
        def _pct_diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
            if a is None or b is None or b == 0:
                return None
            return abs(a - b) / abs(b)

        eps_diff = _pct_diff(primary.eps_estimate, yahoo_item.get("eps_estimate"))
        if eps_diff is not None and eps_diff > 0.2:
            reasons.append("eps_mismatch")

        rev_diff = _pct_diff(primary.revenue_estimate, yahoo_item.get("revenue_estimate"))
        if rev_diff is not None and rev_diff > 0.2:
            reasons.append("revenue_mismatch")

        if reasons:
            return ("low", reasons)
        return ("high", [])
    
    async def get_upcoming_earnings(
        self,
        days_ahead: int = 7,
        sectors: Optional[List[str]] = None,
        include_low_confidence: bool = False
    ) -> List[UpcomingEarnings]:
        """Get upcoming earnings - local calendar -> Perplexity -> Yahoo"""

        # 1) Local calendar (if updated within 7 days)
        local_data = self._load_local_calendar(self.earnings_calendar_path)
        if local_data and local_data.get("earnings"):
            local_earnings: List[UpcomingEarnings] = []
            for item in local_data.get("earnings", []):
                try:
                    local_earnings.append(UpcomingEarnings(
                        symbol=item.get("symbol", ""),
                        company_name=item.get("company_name", ""),
                        earnings_date=date.fromisoformat(item.get("earnings_date", "")),
                        earnings_time=item.get("earnings_time", "AMC"),
                        eps_estimate=item.get("eps_estimate"),
                        revenue_estimate=item.get("revenue_estimate"),
                        beat_rate=item.get("beat_rate"),
                        source=item.get("source", "local"),
                        confidence=item.get("confidence", "medium"),
                        last_verified=date.fromisoformat(item.get("last_verified", local_data.get("last_updated", date.today().isoformat())))
                    ))
                except Exception:
                    continue

            filtered = []
            for item in local_earnings:
                ok, errors = self._validate_upcoming_earnings(item, days_ahead)
                if ok:
                    if include_low_confidence or item.confidence != "low":
                        filtered.append(item)
                else:
                    logger.debug(f"Local earnings invalid for {item.symbol}: {errors}")

            if filtered:
                logger.info(f"Got {len(filtered)} upcoming earnings from local calendar")
                return filtered

        # 2) Perplexity (primary)
        if self.perplexity:
            try:
                earnings = await self.perplexity.get_upcoming_earnings(days_ahead, sectors)
                validated: List[UpcomingEarnings] = []

                for item in earnings:
                    ok, errors = self._validate_upcoming_earnings(item, days_ahead)
                    if not ok:
                        logger.debug(f"Perplexity earnings invalid for {item.symbol}: {errors}")
                        continue

                    # Cross-validate with Yahoo
                    yahoo_items = await self._get_yahoo_earnings_cached(item.symbol)
                    yahoo_upcoming = next((y for y in yahoo_items if y.get("type") == "upcoming"), None)
                    confidence, reasons = self._cross_validate_earnings(item, yahoo_upcoming)
                    item.confidence = confidence
                    if reasons:
                        logger.debug(f"Cross-validation warnings for {item.symbol}: {reasons}")

                    if include_low_confidence or item.confidence != "low":
                        validated.append(item)

                if validated:
                    logger.info(f"Got {len(validated)} upcoming earnings from Perplexity")
                    return validated
            except Exception as e:
                logger.warning(f"Perplexity earnings failed: {e}")

        # 3) Yahoo fallback for popular symbols
        logger.info("Falling back to Yahoo Finance for earnings")
        earnings: List[UpcomingEarnings] = []

        # Check common symbols
        watchlist = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
            "PEP", "KO", "JNJ", "PG", "MRK", "PFE", "BMY",
            "UNH", "CI", "CVS", "HUM",
            "LIN", "APD",
            "CME", "ICE", "CBOE"
        ]

        for symbol in watchlist:
            try:
                yahoo_earnings = await self._get_yahoo_earnings_cached(symbol)
                for earn in yahoo_earnings:
                    if earn.get("type") == "upcoming":
                        earn_date = date.fromisoformat(earn.get("date", ""))
                        if earn_date <= date.today() + timedelta(days=days_ahead):
                            item = UpcomingEarnings(
                                symbol=symbol,
                                company_name=symbol,  # Would need lookup
                                earnings_date=earn_date,
                                earnings_time="AMC",
                                eps_estimate=earn.get("eps_estimate"),
                                revenue_estimate=earn.get("revenue_estimate"),
                                source="yahoo",
                                confidence="medium",
                                last_verified=date.today()
                            )
                            ok, _ = self._validate_upcoming_earnings(item, days_ahead)
                            if ok:
                                earnings.append(item)
            except Exception as e:
                logger.debug(f"Failed to check {symbol}: {e}")
                continue

        return earnings
    
    async def get_earnings_history(
        self,
        symbol: str,
        quarters: int = 8
    ) -> List[EarningsReport]:
        """Get earnings history - tries Perplexity first"""
        
        if self.perplexity:
            try:
                history = await self.perplexity.get_earnings_history(symbol, quarters)
                if history:
                    logger.info(f"Got {len(history)} quarters of earnings history for {symbol}")
                    return history
            except Exception as e:
                logger.warning(f"Perplexity earnings history failed: {e}")
        
        # Fall back to Yahoo
        logger.info(f"Falling back to Yahoo for {symbol} earnings history")
        yahoo_earnings = await self.yahoo.get_earnings_dates(symbol)
        
        history = []
        for earn in yahoo_earnings:
            if earn.get("type") == "historical":
                try:
                    history.append(EarningsReport(
                        symbol=symbol,
                        date=date.fromisoformat(earn.get("date", "1900-01-01")),
                        quarter="",
                        fiscal_year=0,
                        revenue=0,
                        revenue_estimate=0,
                        revenue_surprise_pct=0,
                        eps=earn.get("eps_actual", 0),
                        eps_estimate=earn.get("eps_estimate", 0),
                        eps_surprise_pct=earn.get("surprise_pct", 0) * 100 if earn.get("surprise_pct") else 0
                    ))
                except:
                    continue
        
        return history[:quarters]
    
    async def get_company_profile(self, symbol: str) -> Optional[CompanyFinancials]:
        """Get company financial profile"""
        
        if self.perplexity:
            try:
                profile = await self.perplexity.get_company_financials(symbol)
                if profile:
                    # Enhance with earnings history
                    profile.earnings_history = await self.get_earnings_history(symbol)
                    
                    # Calculate ATLAS-specific scores
                    if profile.earnings_history:
                        moves = [abs(e.stock_move_pct or 0) for e in profile.earnings_history if e.stock_move_pct]
                        if moves:
                            import numpy as np
                            profile.historical_move_avg = np.mean(moves)
                            profile.earnings_predictability_score = 1 / (1 + np.std(moves))
                    
                    return profile
            except Exception as e:
                logger.warning(f"Perplexity profile failed: {e}")
        
        # Fall back to Yahoo
        yahoo_stats = await self.yahoo.get_key_statistics(symbol)
        if yahoo_stats:
            # Build profile from Yahoo data
            key_stats = yahoo_stats.get("defaultKeyStatistics", {})
            fin_data = yahoo_stats.get("financialData", {})
            
            return CompanyFinancials(
                symbol=symbol,
                name=symbol,
                sector="Unknown",
                industry="Unknown",
                market_cap=key_stats.get("marketCap", {}).get("raw", 0),
                pe_ratio=key_stats.get("trailingPE", {}).get("raw"),
                forward_pe=key_stats.get("forwardPE", {}).get("raw"),
                peg_ratio=key_stats.get("pegRatio", {}).get("raw"),
                price_to_book=key_stats.get("priceToBook", {}).get("raw"),
                gross_margin=fin_data.get("grossMargins", {}).get("raw"),
                operating_margin=fin_data.get("operatingMargins", {}).get("raw"),
                net_margin=fin_data.get("profitMargins", {}).get("raw"),
                roe=fin_data.get("returnOnEquity", {}).get("raw"),
                revenue_growth_yoy=fin_data.get("revenueGrowth", {}).get("raw"),
                earnings_growth_yoy=fin_data.get("earningsGrowth", {}).get("raw"),
                total_debt=fin_data.get("totalDebt", {}).get("raw"),
                total_cash=fin_data.get("totalCash", {}).get("raw"),
                debt_to_equity=fin_data.get("debtToEquity", {}).get("raw"),
                current_ratio=fin_data.get("currentRatio", {}).get("raw"),
                analyst_rating=fin_data.get("recommendationKey")
            )
        
        return None
    
    async def get_macro_events(self, days_ahead: int = 14) -> List[MacroEvent]:
        """Get upcoming macro events"""
        # Local calendar first
        local_data = self._load_local_calendar(self.macro_calendar_path)
        if local_data and local_data.get("events"):
            local_events: List[MacroEvent] = []
            for item in local_data.get("events", []):
                try:
                    local_events.append(MacroEvent(
                        event_type=item.get("event_type", ""),
                        event_date=date.fromisoformat(item.get("event_date", "")),
                        event_time=item.get("event_time", ""),
                        description=item.get("description", ""),
                        prior_value=item.get("prior_value"),
                        consensus_estimate=item.get("consensus_estimate"),
                        importance=item.get("importance", "medium")
                    ))
                except Exception:
                    continue

            filtered = []
            for ev in local_events:
                ok, errors = self._validate_macro_event(ev, days_ahead)
                if ok:
                    filtered.append(ev)
                else:
                    logger.debug(f"Local macro event invalid: {errors}")
            if filtered:
                return filtered

        if self.perplexity:
            try:
                events = await self.perplexity.get_macro_events(days_ahead)
                if events:
                    # Validate events
                    valid_events: List[MacroEvent] = []
                    for ev in events:
                        ok, errors = self._validate_macro_event(ev, days_ahead)
                        if ok:
                            valid_events.append(ev)
                        else:
                            logger.debug(f"Perplexity macro invalid: {errors}")
                    return valid_events
            except Exception as e:
                logger.warning(f"Perplexity macro events failed: {e}")

        # No good Yahoo fallback for macro events
        return []
    
    async def check_news(self, symbol: str) -> Dict:
        """Check for breaking news"""
        
        if self.perplexity:
            return await self.perplexity.check_breaking_news(symbol)
        
        return {
            "symbol": symbol,
            "news_summary": "News check unavailable without Perplexity API",
            "timestamp": datetime.now().isoformat()
        }
    
    async def assess_tradability(self, symbol: str) -> Dict:
        """Assess earnings tradability for iron condors"""
        
        if self.perplexity:
            return await self.perplexity.assess_earnings_tradability(symbol)
        
        # Calculate from historical data
        history = await self.get_earnings_history(symbol)
        
        if history:
            import numpy as np
            moves = [abs(e.stock_move_pct or 0) for e in history if e.stock_move_pct]
            
            if moves:
                avg_move = np.mean(moves)
                std_move = np.std(moves)
                
                # Score based on consistency (low std is good)
                consistency_score = max(0, 100 - std_move * 20)
                
                # Score based on move size (2-4% is ideal)
                if 2 <= avg_move <= 4:
                    move_score = 100
                elif avg_move < 2:
                    move_score = avg_move * 50
                else:
                    move_score = max(0, 100 - (avg_move - 4) * 15)
                
                tradability = (consistency_score + move_score) / 2
                
                return {
                    "symbol": symbol,
                    "tradability_score": round(tradability),
                    "avg_move_pct": round(avg_move, 2),
                    "move_std": round(std_move, 2),
                    "quarters_analyzed": len(moves),
                    "recommendation": "Good" if tradability >= 70 else "Caution" if tradability >= 50 else "Avoid"
                }
        
        return {
            "symbol": symbol,
            "tradability_score": 0,
            "recommendation": "Insufficient data"
        }


# ══════════════════════════════════════════════════════════════════════════════
# STANDALONE TEST
# ══════════════════════════════════════════════════════════════════════════════

async def test_financial_service():
    """Test the financial data service"""
    
    perplexity_key = os.getenv("PERPLEXITY_API_KEY")
    
    service = FinancialDataService(perplexity_api_key=perplexity_key)
    
    try:
        print("Testing Financial Data Service...")
        
        # Test upcoming earnings
        print("\n1. Upcoming Earnings:")
        earnings = await service.get_upcoming_earnings(days_ahead=7)
        for e in earnings[:5]:
            print(f"  {e.symbol}: {e.earnings_date} ({e.earnings_time})")
        
        # Test earnings history
        print("\n2. Earnings History (PEP):")
        history = await service.get_earnings_history("PEP", quarters=4)
        for h in history:
            print(f"  {h.quarter}: EPS ${h.eps:.2f} vs ${h.eps_estimate:.2f} ({h.eps_surprise_pct:+.1f}%)")
        
        # Test company profile
        print("\n3. Company Profile (PEP):")
        profile = await service.get_company_profile("PEP")
        if profile:
            print(f"  Name: {profile.name}")
            print(f"  Sector: {profile.sector}")
            print(f"  P/E: {profile.pe_ratio}")
            print(f"  Gross Margin: {profile.gross_margin}")
        
        # Test macro events
        print("\n4. Macro Events:")
        events = await service.get_macro_events(days_ahead=14)
        for e in events[:5]:
            print(f"  {e.event_date}: {e.event_type} - {e.description}")
        
        # Test tradability
        print("\n5. Tradability Assessment (PEP):")
        assessment = await service.assess_tradability("PEP")
        print(f"  Score: {assessment.get('tradability_score')}")
        print(f"  Recommendation: {assessment.get('recommendation')}")
        
        print("\n✓ All tests completed!")
        
    finally:
        await service.close()


if __name__ == "__main__":
    asyncio.run(test_financial_service())
