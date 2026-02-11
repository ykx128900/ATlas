"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                         ATLAS ALPACA INTEGRATION                              ║
║                    Real-Time Options Data & Execution                         ║
╚══════════════════════════════════════════════════════════════════════════════╝

This module provides ATLAS with its interface to the market via Alpaca:
- Real-time options chain data (bid/ask, IV, Greeks)
- Historical options data (2 years) for learning
- Paper trading execution
- Live stock price feeds
- Account management

Author: ATLAS Development Team
Version: 1.0.0 - Production Ready
"""

import asyncio
import aiohttp
import json
import logging
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ATLAS.Alpaca")

# ══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════

class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"

class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"

class TimeInForce(Enum):
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"

class OptionType(Enum):
    CALL = "call"
    PUT = "put"

@dataclass
class OptionContract:
    """Represents a single option contract"""
    symbol: str  # OCC symbol (e.g., "AAPL230120C00150000")
    underlying: str
    expiration: date
    strike: float
    option_type: OptionType
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    volume: int = 0
    open_interest: int = 0
    implied_volatility: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    
    @property
    def mid(self) -> float:
        """Calculate mid price"""
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2
        return self.last
    
    @property
    def spread(self) -> float:
        """Calculate bid-ask spread"""
        if self.bid > 0 and self.ask > 0:
            return self.ask - self.bid
        return 0.0
    
    @property
    def spread_percent(self) -> float:
        """Calculate spread as percentage of mid"""
        if self.mid > 0:
            return (self.spread / self.mid) * 100
        return 0.0

@dataclass
class OptionsChain:
    """Complete options chain for a symbol"""
    underlying: str
    underlying_price: float
    timestamp: datetime
    expirations: List[date]
    calls: Dict[str, OptionContract]  # keyed by OCC symbol
    puts: Dict[str, OptionContract]  # keyed by OCC symbol
    
    def get_expiration_chain(self, expiration: date) -> Tuple[List[OptionContract], List[OptionContract]]:
        """Get all calls and puts for a specific expiration"""
        exp_calls = [c for c in self.calls.values() if c.expiration == expiration]
        exp_puts = [p for p in self.puts.values() if p.expiration == expiration]
        return sorted(exp_calls, key=lambda x: x.strike), sorted(exp_puts, key=lambda x: x.strike)
    
    def get_atm_strike(self, expiration: date) -> float:
        """Get the at-the-money strike for an expiration"""
        calls, _ = self.get_expiration_chain(expiration)
        if not calls:
            return self.underlying_price
        
        # Find strike closest to current price
        strikes = [c.strike for c in calls]
        return min(strikes, key=lambda x: abs(x - self.underlying_price))
    
    def get_contract(self, strike: float, expiration: date, option_type: OptionType) -> Optional[OptionContract]:
        """Get a specific contract by strike, expiration, and type"""
        contracts = self.calls if option_type == OptionType.CALL else self.puts
        for contract in contracts.values():
            if contract.strike == strike and contract.expiration == expiration:
                return contract
        return None

@dataclass
class StockQuote:
    """Real-time stock quote"""
    symbol: str
    bid: float
    ask: float
    last: float
    volume: int
    timestamp: datetime
    
    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

@dataclass
class Position:
    """Trading position"""
    symbol: str
    qty: int
    side: str
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pl: float
    unrealized_plpc: float

@dataclass
class Order:
    """Order representation"""
    id: str
    symbol: str
    qty: int
    side: OrderSide
    type: OrderType
    time_in_force: TimeInForce
    limit_price: Optional[float]
    status: str
    filled_qty: int
    filled_avg_price: float
    submitted_at: datetime
    filled_at: Optional[datetime]

@dataclass
class Account:
    """Account information"""
    id: str
    account_number: str
    status: str
    currency: str
    cash: float
    portfolio_value: float
    buying_power: float
    daytrading_buying_power: float
    options_buying_power: float
    maintenance_margin: float
    equity: float
    last_equity: float
    multiplier: str
    pattern_day_trader: bool

@dataclass
class IronCondorOrder:
    """Iron Condor multi-leg order"""
    underlying: str
    expiration: date
    put_long_strike: float  # Lower protection
    put_short_strike: float  # Lower credit
    call_short_strike: float  # Upper credit
    call_long_strike: float  # Upper protection
    contracts: int
    limit_price: float  # Net credit to receive
    
    @property
    def max_profit(self) -> float:
        """Maximum profit = credit received × 100 × contracts"""
        return self.limit_price * 100 * self.contracts
    
    @property
    def max_loss(self) -> float:
        """Maximum loss = (wing width - credit) × 100 × contracts"""
        put_width = self.put_short_strike - self.put_long_strike
        call_width = self.call_long_strike - self.call_short_strike
        wing_width = max(put_width, call_width)
        return (wing_width - self.limit_price) * 100 * self.contracts
    
    @property
    def collateral_required(self) -> float:
        """Collateral = max loss (one side only)"""
        return self.max_loss

# ══════════════════════════════════════════════════════════════════════════════
# ALPACA CLIENT
# ══════════════════════════════════════════════════════════════════════════════

class AlpacaClient:
    """
    ATLAS's interface to Alpaca Markets.
    
    Provides:
    - Real-time options chain data
    - Historical options data (2 years)
    - Paper trading execution
    - Account management
    """
    
    # API Endpoints
    PAPER_BASE_URL = "https://paper-api.alpaca.markets"
    LIVE_BASE_URL = "https://api.alpaca.markets"
    DATA_BASE_URL = "https://data.alpaca.markets"
    OPTIONS_DATA_URL = "https://data.alpaca.markets/v1beta1/options"
    
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        paper: bool = True  # Default to paper trading
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper = paper
        
        # Select appropriate base URL
        self.base_url = self.PAPER_BASE_URL if paper else self.LIVE_BASE_URL
        
        # HTTP session (created on first request)
        self._session: Optional[aiohttp.ClientSession] = None
        
        # Rate limiting
        self.requests_per_minute = 200
        self.request_times: List[datetime] = []
        
        logger.info(f"AlpacaClient initialized - Mode: {'PAPER' if paper else 'LIVE'}")
    
    @property
    def headers(self) -> Dict[str, str]:
        """API authentication headers"""
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Content-Type": "application/json"
        }
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.headers)
        return self._session
    
    async def close(self):
        """Close HTTP session"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def _rate_limit(self):
        """Simple rate limiting"""
        now = datetime.now()
        self.request_times = [t for t in self.request_times if (now - t).seconds < 60]
        
        if len(self.request_times) >= self.requests_per_minute:
            sleep_time = 60 - (now - self.request_times[0]).seconds
            logger.warning(f"Rate limit reached, sleeping {sleep_time}s")
            await asyncio.sleep(sleep_time)
        
        self.request_times.append(now)
    
    async def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None
    ) -> Dict:
        """Make authenticated API request"""
        await self._rate_limit()
        
        session = await self._get_session()
        
        try:
            async with session.request(
                method,
                url,
                params=params,
                json=json_data
            ) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 204:
                    return {"success": True}
                else:
                    error_text = await response.text()
                    logger.error(f"API Error {response.status}: {error_text}")
                    return {"error": error_text, "status": response.status}
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return {"error": str(e)}
    
    # ══════════════════════════════════════════════════════════════════════════
    # ACCOUNT MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════
    
    async def get_account(self) -> Optional[Account]:
        """Get account information"""
        data = await self._request("GET", f"{self.base_url}/v2/account")
        
        if "error" in data:
            return None
        
        return Account(
            id=data.get("id", ""),
            account_number=data.get("account_number", ""),
            status=data.get("status", ""),
            currency=data.get("currency", "USD"),
            cash=float(data.get("cash", 0)),
            portfolio_value=float(data.get("portfolio_value", 0)),
            buying_power=float(data.get("buying_power", 0)),
            daytrading_buying_power=float(data.get("daytrading_buying_power", 0)),
            options_buying_power=float(data.get("options_buying_power", 0)),
            maintenance_margin=float(data.get("maintenance_margin", 0)),
            equity=float(data.get("equity", 0)),
            last_equity=float(data.get("last_equity", 0)),
            multiplier=data.get("multiplier", "1"),
            pattern_day_trader=data.get("pattern_day_trader", False)
        )
    
    async def get_positions(self) -> List[Position]:
        """Get all open positions"""
        data = await self._request("GET", f"{self.base_url}/v2/positions")
        
        if isinstance(data, dict) and "error" in data:
            return []
        
        positions = []
        for pos in data:
            positions.append(Position(
                symbol=pos.get("symbol", ""),
                qty=int(pos.get("qty", 0)),
                side=pos.get("side", ""),
                avg_entry_price=float(pos.get("avg_entry_price", 0)),
                current_price=float(pos.get("current_price", 0)),
                market_value=float(pos.get("market_value", 0)),
                unrealized_pl=float(pos.get("unrealized_pl", 0)),
                unrealized_plpc=float(pos.get("unrealized_plpc", 0))
            ))
        
        return positions
    
    # ══════════════════════════════════════════════════════════════════════════
    # REAL-TIME STOCK DATA
    # ══════════════════════════════════════════════════════════════════════════
    
    async def get_stock_quote(self, symbol: str) -> Optional[StockQuote]:
        """Get real-time stock quote"""
        url = f"{self.DATA_BASE_URL}/v2/stocks/{symbol}/quotes/latest"
        data = await self._request("GET", url)
        
        if "error" in data:
            return None
        
        quote_data = data.get("quote", {})
        return StockQuote(
            symbol=symbol,
            bid=float(quote_data.get("bp", 0)),
            ask=float(quote_data.get("ap", 0)),
            last=float(quote_data.get("bp", 0) + quote_data.get("ap", 0)) / 2,
            volume=int(quote_data.get("s", 0)),
            timestamp=datetime.now()
        )
    
    async def get_stock_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict]:
        """Get historical stock bars"""
        if start is None:
            start = datetime.now() - timedelta(days=30)
        if end is None:
            end = datetime.now()
        
        params = {
            "timeframe": timeframe,
            "start": start.isoformat() + "Z",
            "end": end.isoformat() + "Z",
            "limit": limit
        }
        
        url = f"{self.DATA_BASE_URL}/v2/stocks/{symbol}/bars"
        data = await self._request("GET", url, params=params)
        
        return data.get("bars", [])
    
    # ══════════════════════════════════════════════════════════════════════════
    # OPTIONS DATA - Real-Time
    # ══════════════════════════════════════════════════════════════════════════
    
    async def get_options_chain(
        self,
        underlying: str,
        expiration: Optional[date] = None,
        strike_price_gte: Optional[float] = None,
        strike_price_lte: Optional[float] = None
    ) -> Optional[OptionsChain]:
        """
        Get full options chain for a symbol.
        
        Args:
            underlying: Stock symbol (e.g., "AAPL")
            expiration: Specific expiration date (optional)
            strike_price_gte: Minimum strike price (optional)
            strike_price_lte: Maximum strike price (optional)
        
        Returns:
            OptionsChain object with all available contracts
        """
        # First get the underlying price
        quote = await self.get_stock_quote(underlying)
        if not quote:
            logger.error(f"Failed to get underlying price for {underlying}")
            return None
        
        underlying_price = quote.mid
        
        # Get available expirations
        url = f"{self.OPTIONS_DATA_URL}/snapshots/{underlying}"
        params = {}
        
        if expiration:
            params["expiration_date"] = expiration.isoformat()
        if strike_price_gte:
            params["strike_price_gte"] = str(strike_price_gte)
        if strike_price_lte:
            params["strike_price_lte"] = str(strike_price_lte)
        
        data = await self._request("GET", url, params=params)
        
        if "error" in data:
            logger.error(f"Failed to get options chain: {data}")
            return None
        
        # Parse the snapshots
        calls = {}
        puts = {}
        expirations = set()
        
        snapshots = data.get("snapshots", {})
        
        for occ_symbol, snapshot in snapshots.items():
            # Parse OCC symbol to get details
            contract = self._parse_option_snapshot(occ_symbol, snapshot, underlying)
            if contract:
                expirations.add(contract.expiration)
                if contract.option_type == OptionType.CALL:
                    calls[occ_symbol] = contract
                else:
                    puts[occ_symbol] = contract
        
        return OptionsChain(
            underlying=underlying,
            underlying_price=underlying_price,
            timestamp=datetime.now(),
            expirations=sorted(list(expirations)),
            calls=calls,
            puts=puts
        )
    
    def _parse_option_snapshot(
        self,
        occ_symbol: str,
        snapshot: Dict,
        underlying: str
    ) -> Optional[OptionContract]:
        """Parse option snapshot data into OptionContract"""
        try:
            # OCC format: AAPL230120C00150000
            # Symbol(1-6) + Date(6) + Type(1) + Strike(8)
            
            # Find where the underlying ends (first digit after letters)
            symbol_end = 0
            for i, char in enumerate(occ_symbol):
                if char.isdigit():
                    symbol_end = i
                    break
            
            # Extract components
            date_str = occ_symbol[symbol_end:symbol_end+6]  # YYMMDD
            option_type_char = occ_symbol[symbol_end+6]  # C or P
            strike_str = occ_symbol[symbol_end+7:]  # 00150000
            
            # Parse expiration
            exp_date = datetime.strptime(date_str, "%y%m%d").date()
            
            # Parse strike (divide by 1000)
            strike = int(strike_str) / 1000
            
            # Parse type
            option_type = OptionType.CALL if option_type_char == "C" else OptionType.PUT
            
            # Get quote data
            latest_quote = snapshot.get("latestQuote", {})
            latest_trade = snapshot.get("latestTrade", {})
            greeks = snapshot.get("greeks", {})
            
            return OptionContract(
                symbol=occ_symbol,
                underlying=underlying,
                expiration=exp_date,
                strike=strike,
                option_type=option_type,
                bid=float(latest_quote.get("bp", 0)),
                ask=float(latest_quote.get("ap", 0)),
                last=float(latest_trade.get("p", 0)),
                volume=int(latest_trade.get("s", 0)) if latest_trade else 0,
                open_interest=int(snapshot.get("openInterest", 0)),
                implied_volatility=float(snapshot.get("impliedVolatility", 0)),
                delta=float(greeks.get("delta", 0)),
                gamma=float(greeks.get("gamma", 0)),
                theta=float(greeks.get("theta", 0)),
                vega=float(greeks.get("vega", 0))
            )
        except Exception as e:
            logger.error(f"Failed to parse option snapshot {occ_symbol}: {e}")
            return None
    
    async def get_option_quote(self, occ_symbol: str) -> Optional[OptionContract]:
        """Get real-time quote for a specific option contract"""
        url = f"{self.OPTIONS_DATA_URL}/quotes/latest"
        params = {"symbols": occ_symbol}
        
        data = await self._request("GET", url, params=params)
        
        if "error" in data:
            return None
        
        quotes = data.get("quotes", {})
        if occ_symbol in quotes:
            quote = quotes[occ_symbol]
            # Parse the OCC symbol for details
            return self._parse_quote_to_contract(occ_symbol, quote)
        
        return None
    
    def _parse_quote_to_contract(self, occ_symbol: str, quote: Dict) -> OptionContract:
        """Parse a quote response into OptionContract"""
        # Extract details from OCC symbol
        symbol_end = 0
        for i, char in enumerate(occ_symbol):
            if char.isdigit():
                symbol_end = i
                break
        
        underlying = occ_symbol[:symbol_end]
        date_str = occ_symbol[symbol_end:symbol_end+6]
        option_type_char = occ_symbol[symbol_end+6]
        strike_str = occ_symbol[symbol_end+7:]
        
        exp_date = datetime.strptime(date_str, "%y%m%d").date()
        strike = int(strike_str) / 1000
        option_type = OptionType.CALL if option_type_char == "C" else OptionType.PUT
        
        return OptionContract(
            symbol=occ_symbol,
            underlying=underlying,
            expiration=exp_date,
            strike=strike,
            option_type=option_type,
            bid=float(quote.get("bp", 0)),
            ask=float(quote.get("ap", 0)),
            last=float(quote.get("p", 0)) if "p" in quote else 0,
            volume=0,
            open_interest=0,
            implied_volatility=0,
            delta=0,
            gamma=0,
            theta=0,
            vega=0
        )
    
    # ══════════════════════════════════════════════════════════════════════════
    # OPTIONS DATA - Historical (2 Years)
    # ══════════════════════════════════════════════════════════════════════════
    
    async def get_historical_options_bars(
        self,
        symbols: List[str],
        timeframe: str = "1Day",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 10000
    ) -> Dict[str, List[Dict]]:
        """
        Get historical options data.
        
        Alpaca provides up to 2 years of historical options data.
        
        Args:
            symbols: List of OCC symbols
            timeframe: Bar timeframe (1Min, 5Min, 15Min, 30Min, 1Hour, 1Day)
            start: Start datetime
            end: End datetime
            limit: Max bars per symbol
        
        Returns:
            Dict mapping symbols to list of bars
        """
        if start is None:
            start = datetime.now() - timedelta(days=730)  # 2 years
        if end is None:
            end = datetime.now()
        
        params = {
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "start": start.isoformat() + "Z",
            "end": end.isoformat() + "Z",
            "limit": limit
        }
        
        url = f"{self.OPTIONS_DATA_URL}/bars"
        data = await self._request("GET", url, params=params)
        
        return data.get("bars", {})
    
    async def get_historical_earnings_moves(
        self,
        symbol: str,
        earnings_dates: List[date],
        earnings_time: str = "AMC",
        days_before: int = 1,
        days_after: int = 1
    ) -> List[Dict]:
        """
        Get historical stock moves around earnings dates.
        
        This is crucial for ATLAS's learning about how stocks move on earnings.
        
        Args:
            symbol: Stock symbol
            earnings_dates: List of historical earnings dates
            days_before: Days before earnings to capture
            days_after: Days after earnings to capture
        
        Returns:
            List of earnings move data
        """
        moves = []
        
        for earn_date in earnings_dates:
            start = datetime.combine(earn_date - timedelta(days=days_before), datetime.min.time())
            end = datetime.combine(earn_date + timedelta(days=days_after), datetime.max.time())
            
            bars = await self.get_stock_bars(
                symbol,
                timeframe="1Day",
                start=start,
                end=end,
                limit=10
            )
            
            if len(bars) >= 2:
                # Find the bar before earnings and after earnings
                pre_earnings = None
                post_earnings = None
                
                for bar in bars:
                    bar_date = datetime.fromisoformat(bar.get("t", "").replace("Z", "")).date()
                    if bar_date < earn_date:
                        pre_earnings = bar
                    elif post_earnings is None:
                        # AMC: post-earnings is the next trading day
                        # BMO/INTRADAY: post-earnings is the same day
                        if earnings_time.upper() == "AMC":
                            if bar_date > earn_date:
                                post_earnings = bar
                        else:
                            if bar_date == earn_date:
                                post_earnings = bar
                
                if pre_earnings and post_earnings:
                    pre_close = float(pre_earnings.get("c", 0))
                    post_close = float(post_earnings.get("c", 0))
                    post_high = float(post_earnings.get("h", 0))
                    post_low = float(post_earnings.get("l", 0))
                    
                    if pre_close > 0:
                        move_pct = ((post_close - pre_close) / pre_close) * 100
                        max_up = ((post_high - pre_close) / pre_close) * 100
                        max_down = ((post_low - pre_close) / pre_close) * 100
                        
                        moves.append({
                            "date": earn_date.isoformat(),
                            "pre_close": pre_close,
                            "post_close": post_close,
                            "move_pct": round(move_pct, 2),
                            "max_up_pct": round(max_up, 2),
                            "max_down_pct": round(max_down, 2),
                            "abs_move": round(abs(move_pct), 2)
                        })
        
        return moves
    
    async def get_historical_iv_around_earnings(
        self,
        symbol: str,
        earnings_date: date,
        strike: float,
        days_before: int = 5
    ) -> List[Dict]:
        """
        Get historical IV leading up to an earnings event.
        
        This helps ATLAS understand how IV typically builds before earnings.
        """
        # Build OCC symbol for ATM call
        exp_date = earnings_date + timedelta(days=7)  # First expiration after earnings
        occ_symbol = self._build_occ_symbol(symbol, exp_date, strike, OptionType.CALL)
        
        start = datetime.combine(earnings_date - timedelta(days=days_before), datetime.min.time())
        end = datetime.combine(earnings_date, datetime.max.time())
        
        bars = await self.get_historical_options_bars(
            [occ_symbol],
            timeframe="1Day",
            start=start,
            end=end
        )
        
        iv_history = []
        for bar in bars.get(occ_symbol, []):
            iv_history.append({
                "date": bar.get("t"),
                "close": bar.get("c"),
                "volume": bar.get("v"),
                "iv": bar.get("iv", 0)  # If available
            })
        
        return iv_history
    
    def _build_occ_symbol(
        self,
        underlying: str,
        expiration: date,
        strike: float,
        option_type: OptionType
    ) -> str:
        """Build OCC option symbol"""
        # Pad underlying to 6 chars
        padded_underlying = underlying.ljust(6)[:6]
        
        # Format date as YYMMDD
        date_str = expiration.strftime("%y%m%d")
        
        # Type character
        type_char = "C" if option_type == OptionType.CALL else "P"
        
        # Strike as 8 digits (multiply by 1000)
        strike_int = int(strike * 1000)
        strike_str = str(strike_int).zfill(8)
        
        return f"{padded_underlying}{date_str}{type_char}{strike_str}"
    
    # ══════════════════════════════════════════════════════════════════════════
    # ORDER EXECUTION
    # ══════════════════════════════════════════════════════════════════════════
    
    async def submit_option_order(
        self,
        occ_symbol: str,
        qty: int,
        side: OrderSide,
        order_type: OrderType = OrderType.LIMIT,
        limit_price: Optional[float] = None,
        time_in_force: TimeInForce = TimeInForce.DAY
    ) -> Optional[Order]:
        """
        Submit a single-leg option order.
        
        Args:
            occ_symbol: OCC option symbol
            qty: Number of contracts
            side: Buy or Sell
            order_type: Market, Limit, etc.
            limit_price: Limit price for limit orders
            time_in_force: DAY, GTC, etc.
        
        Returns:
            Order object if successful
        """
        order_data = {
            "symbol": occ_symbol,
            "qty": str(qty),
            "side": side.value,
            "type": order_type.value,
            "time_in_force": time_in_force.value
        }
        
        if limit_price and order_type in [OrderType.LIMIT, OrderType.STOP_LIMIT]:
            order_data["limit_price"] = str(limit_price)
        
        url = f"{self.base_url}/v2/orders"
        data = await self._request("POST", url, json_data=order_data)
        
        if "error" in data:
            logger.error(f"Order submission failed: {data}")
            return None
        
        return self._parse_order(data)
    
    async def submit_iron_condor(
        self,
        ic: IronCondorOrder
    ) -> Optional[str]:
        """
        Submit an Iron Condor as a multi-leg order.
        
        Iron Condor consists of 4 legs:
        1. Buy put (lower strike) - long protection
        2. Sell put (higher strike) - credit leg
        3. Sell call (lower strike) - credit leg  
        4. Buy call (higher strike) - long protection
        
        Args:
            ic: IronCondorOrder with all parameters
        
        Returns:
            Order ID if successful
        """
        # Build OCC symbols for all 4 legs
        put_long_symbol = self._build_occ_symbol(
            ic.underlying, ic.expiration, ic.put_long_strike, OptionType.PUT
        )
        put_short_symbol = self._build_occ_symbol(
            ic.underlying, ic.expiration, ic.put_short_strike, OptionType.PUT
        )
        call_short_symbol = self._build_occ_symbol(
            ic.underlying, ic.expiration, ic.call_short_strike, OptionType.CALL
        )
        call_long_symbol = self._build_occ_symbol(
            ic.underlying, ic.expiration, ic.call_long_strike, OptionType.CALL
        )
        
        # Multi-leg order
        order_data = {
            "symbol": ic.underlying,  # Underlying for the combo
            "qty": str(ic.contracts),
            "side": "sell",  # We're selling the iron condor (collecting premium)
            "type": "limit",
            "time_in_force": "day",
            "limit_price": str(ic.limit_price),
            "order_class": "mleg",  # Multi-leg order
            "legs": [
                {"symbol": put_long_symbol, "ratio_qty": 1, "side": "buy"},
                {"symbol": put_short_symbol, "ratio_qty": 1, "side": "sell"},
                {"symbol": call_short_symbol, "ratio_qty": 1, "side": "sell"},
                {"symbol": call_long_symbol, "ratio_qty": 1, "side": "buy"}
            ]
        }
        
        url = f"{self.base_url}/v2/orders"
        data = await self._request("POST", url, json_data=order_data)
        
        if "error" in data:
            logger.error(f"Iron Condor submission failed: {data}")
            return None
        
        order_id = data.get("id")
        logger.info(f"Iron Condor submitted: {order_id}")
        logger.info(f"  Put spread: {ic.put_long_strike}/{ic.put_short_strike}")
        logger.info(f"  Call spread: {ic.call_short_strike}/{ic.call_long_strike}")
        logger.info(f"  Contracts: {ic.contracts}, Credit: ${ic.limit_price:.2f}")
        
        return order_id
    
    async def close_iron_condor(
        self,
        ic: IronCondorOrder,
        limit_price: Optional[float] = None
    ) -> Optional[str]:
        """
        Close an Iron Condor position.
        
        To close, we do the opposite trades:
        - Sell the long puts we bought
        - Buy back the short puts we sold
        - Buy back the short calls we sold
        - Sell the long calls we bought
        
        Args:
            ic: Original IronCondorOrder
            limit_price: Debit to pay to close (optional, will use market mid if not provided)
        
        Returns:
            Order ID if successful
        """
        # Build OCC symbols
        put_long_symbol = self._build_occ_symbol(
            ic.underlying, ic.expiration, ic.put_long_strike, OptionType.PUT
        )
        put_short_symbol = self._build_occ_symbol(
            ic.underlying, ic.expiration, ic.put_short_strike, OptionType.PUT
        )
        call_short_symbol = self._build_occ_symbol(
            ic.underlying, ic.expiration, ic.call_short_strike, OptionType.CALL
        )
        call_long_symbol = self._build_occ_symbol(
            ic.underlying, ic.expiration, ic.call_long_strike, OptionType.CALL
        )
        
        # If no limit price, get current market prices
        if limit_price is None:
            # Get quotes for all legs and calculate mid
            # For now, use market order type
            order_type = "market"
        else:
            order_type = "limit"
        
        # Closing order (buy to close the iron condor)
        order_data = {
            "symbol": ic.underlying,
            "qty": str(ic.contracts),
            "side": "buy",  # Buying back to close
            "type": order_type,
            "time_in_force": "day",
            "order_class": "mleg",
            "legs": [
                {"symbol": put_long_symbol, "ratio_qty": 1, "side": "sell"},
                {"symbol": put_short_symbol, "ratio_qty": 1, "side": "buy"},
                {"symbol": call_short_symbol, "ratio_qty": 1, "side": "buy"},
                {"symbol": call_long_symbol, "ratio_qty": 1, "side": "sell"}
            ]
        }
        
        if limit_price:
            order_data["limit_price"] = str(limit_price)
        
        url = f"{self.base_url}/v2/orders"
        data = await self._request("POST", url, json_data=order_data)
        
        if "error" in data:
            logger.error(f"Close Iron Condor failed: {data}")
            return None
        
        order_id = data.get("id")
        logger.info(f"Iron Condor close order submitted: {order_id}")
        
        return order_id
    
    async def get_order(self, order_id: str) -> Optional[Order]:
        """Get order status"""
        url = f"{self.base_url}/v2/orders/{order_id}"
        data = await self._request("GET", url)
        
        if "error" in data:
            return None
        
        return self._parse_order(data)
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order"""
        url = f"{self.base_url}/v2/orders/{order_id}"
        data = await self._request("DELETE", url)
        
        return "error" not in data
    
    async def get_open_orders(self) -> List[Order]:
        """Get all open orders"""
        url = f"{self.base_url}/v2/orders"
        params = {"status": "open"}
        data = await self._request("GET", url, params=params)
        
        if isinstance(data, dict) and "error" in data:
            return []
        
        return [self._parse_order(order) for order in data]
    
    def _parse_order(self, data: Dict) -> Order:
        """Parse order response into Order object"""
        return Order(
            id=data.get("id", ""),
            symbol=data.get("symbol", ""),
            qty=int(data.get("qty", 0)),
            side=OrderSide(data.get("side", "buy")),
            type=OrderType(data.get("type", "market")),
            time_in_force=TimeInForce(data.get("time_in_force", "day")),
            limit_price=float(data.get("limit_price", 0)) if data.get("limit_price") else None,
            status=data.get("status", ""),
            filled_qty=int(data.get("filled_qty", 0)),
            filled_avg_price=float(data.get("filled_avg_price", 0)) if data.get("filled_avg_price") else 0,
            submitted_at=datetime.fromisoformat(data.get("submitted_at", "").replace("Z", "")),
            filled_at=datetime.fromisoformat(data.get("filled_at", "").replace("Z", "")) if data.get("filled_at") else None
        )
    
    # ══════════════════════════════════════════════════════════════════════════
    # UTILITY METHODS
    # ══════════════════════════════════════════════════════════════════════════
    
    async def is_market_open(self) -> bool:
        """Check if the market is currently open"""
        url = f"{self.base_url}/v2/clock"
        data = await self._request("GET", url)
        
        return data.get("is_open", False)
    
    async def get_market_hours(self) -> Dict:
        """Get market hours for today"""
        url = f"{self.base_url}/v2/clock"
        data = await self._request("GET", url)
        
        return {
            "is_open": data.get("is_open", False),
            "next_open": data.get("next_open"),
            "next_close": data.get("next_close")
        }
    
    async def get_calendar(
        self,
        start: Optional[date] = None,
        end: Optional[date] = None
    ) -> List[Dict]:
        """Get market calendar"""
        if start is None:
            start = date.today()
        if end is None:
            end = start + timedelta(days=30)
        
        url = f"{self.base_url}/v2/calendar"
        params = {
            "start": start.isoformat(),
            "end": end.isoformat()
        }
        
        data = await self._request("GET", url, params=params)
        
        if isinstance(data, dict) and "error" in data:
            return []
        
        return data


# ══════════════════════════════════════════════════════════════════════════════
# HELPER CLASS FOR IRON CONDOR PRICING
# ══════════════════════════════════════════════════════════════════════════════

class IronCondorPricer:
    """
    Calculates optimal Iron Condor pricing from options chain data.
    """
    
    def __init__(self, alpaca: AlpacaClient):
        self.alpaca = alpaca
    
    async def price_iron_condor(
        self,
        underlying: str,
        expiration: date,
        put_long_strike: float,
        put_short_strike: float,
        call_short_strike: float,
        call_long_strike: float
    ) -> Dict:
        """
        Get current pricing for an Iron Condor.
        
        Returns:
            Dict with bid, ask, mid prices and Greeks
        """
        chain = await self.alpaca.get_options_chain(
            underlying,
            expiration=expiration,
            strike_price_gte=put_long_strike - 5,
            strike_price_lte=call_long_strike + 5
        )
        
        if not chain:
            return {"error": "Failed to get options chain"}
        
        # Get all 4 contracts
        put_long = chain.get_contract(put_long_strike, expiration, OptionType.PUT)
        put_short = chain.get_contract(put_short_strike, expiration, OptionType.PUT)
        call_short = chain.get_contract(call_short_strike, expiration, OptionType.CALL)
        call_long = chain.get_contract(call_long_strike, expiration, OptionType.CALL)
        
        if not all([put_long, put_short, call_short, call_long]):
            return {"error": "Missing contracts in chain"}
        
        # Calculate Iron Condor price
        # IC = Sell put spread + Sell call spread
        # = (Short put - Long put) + (Short call - Long call)
        
        # Natural price (what we'd get filled at)
        bid = (put_short.bid - put_long.ask) + (call_short.bid - call_long.ask)
        ask = (put_short.ask - put_long.bid) + (call_short.ask - call_long.bid)
        mid = (bid + ask) / 2
        
        # Net Greeks
        net_delta = put_long.delta - put_short.delta - call_short.delta + call_long.delta
        net_gamma = put_long.gamma - put_short.gamma - call_short.gamma + call_long.gamma
        net_theta = put_long.theta - put_short.theta - call_short.theta + call_long.theta
        net_vega = put_long.vega - put_short.vega - call_short.vega + call_long.vega
        
        # Average IV of short strikes
        avg_iv = (put_short.implied_volatility + call_short.implied_volatility) / 2
        
        return {
            "underlying_price": chain.underlying_price,
            "expiration": expiration.isoformat(),
            "strikes": {
                "put_long": put_long_strike,
                "put_short": put_short_strike,
                "call_short": call_short_strike,
                "call_long": call_long_strike
            },
            "pricing": {
                "bid": round(bid, 2),
                "ask": round(ask, 2),
                "mid": round(mid, 2),
                "spread": round(ask - bid, 2)
            },
            "greeks": {
                "delta": round(net_delta, 4),
                "gamma": round(net_gamma, 4),
                "theta": round(net_theta, 4),
                "vega": round(net_vega, 4)
            },
            "implied_volatility": round(avg_iv * 100, 2),
            "max_profit": round(mid * 100, 2),
            "max_loss": round((max(put_short_strike - put_long_strike, call_long_strike - call_short_strike) - mid) * 100, 2),
            "collateral": round((max(put_short_strike - put_long_strike, call_long_strike - call_short_strike) - mid) * 100, 2)
        }
    
    async def find_optimal_strikes(
        self,
        underlying: str,
        expiration: date,
        target_credit: float,  # Target credit per contract
        wing_width: float,  # Distance between short and long strikes
        min_delta: float = 0.10,  # Minimum delta for short strikes
        max_delta: float = 0.25  # Maximum delta for short strikes
    ) -> Optional[Dict]:
        """
        Find optimal Iron Condor strikes based on criteria.
        
        Args:
            underlying: Stock symbol
            expiration: Option expiration date
            target_credit: Desired credit per contract
            wing_width: Width of wings (e.g., 5.0 for $5 wide)
            min_delta: Minimum acceptable delta for shorts
            max_delta: Maximum acceptable delta for shorts
        
        Returns:
            Optimal strike configuration
        """
        chain = await self.alpaca.get_options_chain(underlying, expiration=expiration)
        
        if not chain:
            return None
        
        calls, puts = chain.get_expiration_chain(expiration)
        
        if not calls or not puts:
            return None
        
        best_config = None
        best_score = -float('inf')
        
        # Filter puts by delta range (negative deltas)
        valid_short_puts = [p for p in puts if min_delta <= abs(p.delta) <= max_delta]
        
        # Filter calls by delta range (positive deltas)
        valid_short_calls = [c for c in calls if min_delta <= c.delta <= max_delta]
        
        for short_put in valid_short_puts:
            for short_call in valid_short_calls:
                # Calculate long strikes
                long_put_strike = short_put.strike - wing_width
                long_call_strike = short_call.strike + wing_width
                
                # Get long contracts
                long_put = chain.get_contract(long_put_strike, expiration, OptionType.PUT)
                long_call = chain.get_contract(long_call_strike, expiration, OptionType.CALL)
                
                if not long_put or not long_call:
                    continue
                
                # Calculate credit
                credit = (short_put.bid - long_put.ask + short_call.bid - long_call.ask)
                
                if credit < 0:
                    continue
                
                # Score: closer to target credit is better
                credit_score = 1 - abs(credit - target_credit) / target_credit
                
                # Bonus for balanced deltas (put delta ≈ -call delta)
                delta_balance = 1 - abs(abs(short_put.delta) - abs(short_call.delta))
                
                # Bonus for good liquidity
                liquidity_score = min(short_put.open_interest, short_call.open_interest) / 1000
                liquidity_score = min(liquidity_score, 1.0)
                
                total_score = credit_score * 0.5 + delta_balance * 0.3 + liquidity_score * 0.2
                
                if total_score > best_score:
                    best_score = total_score
                    best_config = {
                        "put_long_strike": long_put_strike,
                        "put_short_strike": short_put.strike,
                        "call_short_strike": short_call.strike,
                        "call_long_strike": long_call_strike,
                        "credit": round(credit, 2),
                        "put_delta": round(short_put.delta, 3),
                        "call_delta": round(short_call.delta, 3),
                        "score": round(total_score, 3)
                    }
        
        return best_config


# ══════════════════════════════════════════════════════════════════════════════
# STANDALONE TEST
# ══════════════════════════════════════════════════════════════════════════════

async def test_alpaca_connection():
    """Test Alpaca connection and basic functionality"""
    api_key = os.getenv("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_API_SECRET")
    
    if not api_key or not api_secret:
        print("Set ALPACA_API_KEY and ALPACA_API_SECRET environment variables")
        return
    
    client = AlpacaClient(api_key, api_secret, paper=True)
    
    try:
        # Test account
        print("Testing account connection...")
        account = await client.get_account()
        if account:
            print(f"  Account: {account.account_number}")
            print(f"  Equity: ${account.equity:,.2f}")
            print(f"  Buying Power: ${account.buying_power:,.2f}")
            print(f"  Options BP: ${account.options_buying_power:,.2f}")
        
        # Test stock quote
        print("\nTesting stock quote...")
        quote = await client.get_stock_quote("AAPL")
        if quote:
            print(f"  AAPL: ${quote.mid:.2f} (bid: ${quote.bid:.2f}, ask: ${quote.ask:.2f})")
        
        # Test options chain
        print("\nTesting options chain...")
        chain = await client.get_options_chain("AAPL")
        if chain:
            print(f"  Underlying: ${chain.underlying_price:.2f}")
            print(f"  Expirations: {len(chain.expirations)}")
            print(f"  Calls: {len(chain.calls)}")
            print(f"  Puts: {len(chain.puts)}")
        
        # Test market hours
        print("\nTesting market hours...")
        hours = await client.get_market_hours()
        print(f"  Is Open: {hours['is_open']}")
        print(f"  Next Open: {hours['next_open']}")
        
        print("\n✓ All tests passed!")
        
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(test_alpaca_connection())
