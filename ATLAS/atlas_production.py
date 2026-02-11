"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                          ATLAS PRODUCTION SYSTEM                              ║
║              Complete Autonomous Trading System for Paper Trading             ║
╚══════════════════════════════════════════════════════════════════════════════╝

This is the main entry point for ATLAS in production mode.

Features:
- Automatic daily trading cycle
- 5-minute position monitoring
- Real-time options data via Alpaca
- Financial data via Perplexity + Yahoo + Google Finance
- State persistence across sessions
- Comprehensive logging
- Paper trading execution

Author: ATLAS Development Team
Version: 1.0.0 - Production Ready for Monday
"""

import asyncio
import json
import re
import logging
import os
import signal
import sys
from datetime import datetime, timedelta, date, time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
import argparse

# ATLAS Components
from atlas_core import (
    ATLASMood, ATLASState, ATLASPersonality, AccountConfig,
    EventType, Event, MonteCarloEngine, FinancialAnalyzer
)
from atlas_alpaca import (
    AlpacaClient, IronCondorOrder, OptionsChain, IronCondorPricer,
    OptionType
)
from atlas_financial import (
    FinancialDataService, UpcomingEarnings, CompanyFinancials,
    MacroEvent
)
from atlas_monitor import (
    MonitoringEngine, MonitoringConfig, MonitoredPosition,
    Alert, AlertLevel, ExitReason
)
from atlas_clock import MarketClock
from atlas_context import StrategicContextEngine
from atlas_brain import NvidiaBrain
from atlas_db import (
    init_db,
    migrate_json_if_needed,
    load_state_dict,
    set_state,
    load_all_trades,
    insert_trade,
    update_trade_outcome,
    insert_intelligence
)

# Configure logging
def setup_logging(log_dir: str = "logs"):
    """Setup comprehensive logging"""
    Path(log_dir).mkdir(exist_ok=True)
    
    log_file = f"{log_dir}/atlas_{datetime.now().strftime('%Y%m%d')}.log"
    
    # Configure root logger
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger("ATLAS")

logger = setup_logging()


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ATLASProductionConfig:
    """Complete production configuration for ATLAS"""
    
    # API Keys (set via environment variables)
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    perplexity_api_key: str = ""
    nvidia_api_key: str = ""
    
    # Trading Mode
    paper_trading: bool = True  # ALWAYS True for safety
    
    # Account Settings
    total_capital: float = 40000.0
    liquid_capital: float = 20000.0
    min_collateral_per_trade: float = 7500.0
    max_risk_per_trade: float = 5000.0
    max_concurrent_trades: int = 2
    max_daily_trades: int = 2
    
    # Trading Parameters
    min_edge_threshold: float = 1.0  # Minimum edge % to trade
    min_confidence: float = 0.60  # Minimum confidence to trade
    profit_target_pct: float = 50.0  # Take profit at 50% of max
    max_loss_pct: float = 75.0  # Stop loss at 75% of max loss
    
    # Monitoring Settings
    position_check_interval: int = 300  # 5 minutes
    news_check_interval: int = 300  # 5 minutes

    # Brain runtime policy
    brain_fail_mode: str = "block"  # block|warn|allow
    brain_warn_confidence_penalty: float = 0.15
    brain_timeout_seconds: int = 45
    
    # Scheduling
    daily_scan_time: str = "09:00"  # Time to run daily scan (ET)
    entry_window_start: str = "15:00"  # Entry window start (ET)
    entry_window_end: str = "15:45"  # Entry window end (ET)
    timezone: str = "America/New_York"

    # Data paths
    earnings_calendar_path: str = "data/earnings_calendar.json"
    macro_calendar_path: str = "data/macro_calendar.json"
    
    # Persistence
    state_file: str = "atlas_state.json"
    positions_file: str = "atlas_positions.json"
    history_file: str = "atlas_history.json"
    db_path: str = "atlas.db"

    # Liquidity & pricing filters
    min_open_interest: int = 100
    min_volume: int = 10
    max_spread_pct: float = 25.0
    min_credit_to_width: float = 0.20

    # Portfolio risk caps
    max_total_collateral: float = 15000.0
    max_symbol_collateral: float = 7500.0
    max_consecutive_losses: int = 3
    daily_loss_limit_pct: float = 0.02
    
    # Target Symbols
    watchlist: List[str] = None
    
    def __post_init__(self):
        # Load from environment
        self.alpaca_api_key = os.getenv("ALPACA_API_KEY", self.alpaca_api_key)
        self.alpaca_api_secret = os.getenv("ALPACA_API_SECRET", self.alpaca_api_secret)
        self.perplexity_api_key = os.getenv("PERPLEXITY_API_KEY", self.perplexity_api_key)
        self.nvidia_api_key = os.getenv("NVIDIA_API_KEY", self.nvidia_api_key)
        self.brain_fail_mode = (self.brain_fail_mode or "block").lower()
        if self.brain_fail_mode not in {"block", "warn", "allow"}:
            self.brain_fail_mode = "block"
        
        # Default watchlist
        if self.watchlist is None:
            self.watchlist = [
                # Consumer Staples (predictable 1-3% moves)
                "PEP", "KO", "PG", "CL", "KHC", "GIS", "K", "CAG",
                # Big Pharma (stable 2-4% moves)
                "MRK", "PFE", "BMY", "ABBV", "LLY", "JNJ",
                # Healthcare Insurers (regulated revenue)
                "UNH", "CI", "CVS", "HUM", "ELV",
                # Financial Infrastructure (toll roads)
                "CME", "ICE", "CBOE", "NDAQ", "MSCI",
                # Industrial Gases (duopoly)
                "LIN", "APD",
                # Utilities (very predictable)
                "NEE", "DUK", "SO", "D",
                # Defense (stable, predictable)
                "RTX", "LMT", "NOC", "GD",
                # Telecom (stable)
                "VZ", "T",
                # Index ETFs for macro events
                "SPY", "QQQ", "IWM"
            ]
    
    @classmethod
    def from_file(cls, filepath: str) -> "ATLASProductionConfig":
        """Load configuration from JSON file"""
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                data = json.load(f)
                return cls(**data)
        return cls()
    
    def save(self, filepath: str):
        """Save configuration to JSON file"""
        with open(filepath, 'w') as f:
            json.dump(asdict(self), f, indent=2, default=list)


# ══════════════════════════════════════════════════════════════════════════════
# ATLAS PRODUCTION SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

class ATLASProduction:
    """
    The complete ATLAS production system.
    
    This is ATLAS running in production - a sentient trading entity that:
    - Wakes up each morning to scan for opportunities
    - Thinks deeply about each candidate
    - Makes autonomous trading decisions
    - Monitors positions continuously (every 5 minutes)
    - Learns from every outcome
    """
    
    def __init__(self, config: ATLASProductionConfig):
        self.config = config
        
        # Validate configuration
        self._validate_config()
        
        # Initialize ATLAS state
        self.state = ATLASState()
        self.account = AccountConfig(
            total_capital=config.total_capital,
            liquid_capital=config.liquid_capital,
            min_collateral_per_trade=config.min_collateral_per_trade,
            max_risk_per_trade=config.max_risk_per_trade,
            max_concurrent_trades=config.max_concurrent_trades,
            max_daily_trades=config.max_daily_trades
        )
        
        # Initialize components
        self.alpaca = AlpacaClient(
            config.alpaca_api_key,
            config.alpaca_api_secret,
            paper=config.paper_trading
        )
        
        self.financial = FinancialDataService(
            perplexity_api_key=config.perplexity_api_key,
            earnings_calendar_path=config.earnings_calendar_path,
            macro_calendar_path=config.macro_calendar_path
        )
        
        self.pricer = IronCondorPricer(self.alpaca)
        self.monte_carlo = MonteCarloEngine(n_simulations=50000)
        self.analyzer = FinancialAnalyzer()
        
        # Initialize monitoring
        monitor_config = MonitoringConfig(
            check_interval_seconds=config.position_check_interval,
            news_check_interval_seconds=config.news_check_interval,
            profit_target_pct=config.profit_target_pct,
            max_loss_pct=config.max_loss_pct
        )
        self.monitor = MonitoringEngine(self.alpaca, self.financial, monitor_config)
        self.clock = MarketClock(self.alpaca, config.timezone)
        self.context_engine = StrategicContextEngine(self.financial)
        self.brain = NvidiaBrain(api_key=config.nvidia_api_key)
        
        # Set up monitoring callbacks
        self.monitor.on_alert = self._handle_alert
        self.monitor.on_exit_signal = self._handle_exit_signal
        
        # Running state
        self.is_running = False
        self._main_task: Optional[asyncio.Task] = None
        self._scheduler_task: Optional[asyncio.Task] = None
        
        # Trading state
        self.today_trades = 0
        self.pending_orders: Dict[str, Dict] = {}
        self.trade_history: List[Dict] = []
        self.pending_trades: List[Dict] = []
        self.trading_halted_today: bool = False
        self.consecutive_losses: int = 0
        self.daily_realized_pnl: float = 0.0
        self._daily_pnl_date: Optional[date] = None
        
        # Initialize database & migrate JSON if needed
        init_db(self.config.db_path)
        migrate_json_if_needed(self.config.db_path, self.config.state_file, self.config.history_file)

        # Load persisted state
        self._load_state()
        
        logger.info("=" * 60)
        logger.info("ATLAS PRODUCTION SYSTEM INITIALIZED")
        logger.info("=" * 60)
        logger.info(f"Mode: {'PAPER' if config.paper_trading else 'LIVE'} TRADING")
        logger.info(f"Capital: ${config.total_capital:,.2f}")
        logger.info(f"Max Risk/Trade: ${config.max_risk_per_trade:,.2f}")
        logger.info(f"Monitoring Interval: {config.position_check_interval}s")
        logger.info("=" * 60)
    
    def _validate_config(self):
        """Validate configuration"""
        if not self.config.alpaca_api_key:
            raise ValueError("ALPACA_API_KEY is required")
        if not self.config.alpaca_api_secret:
            raise ValueError("ALPACA_API_SECRET is required")
        
        if not self.config.paper_trading:
            logger.warning("⚠️ LIVE TRADING MODE - Are you sure?")
    
    # ══════════════════════════════════════════════════════════════════════════
    # STATE PERSISTENCE
    # ══════════════════════════════════════════════════════════════════════════
    
    def _load_state(self):
        """Load persisted state from SQLite"""
        try:
            state = load_state_dict(self.config.db_path)
            if state:
                # Values are stored as JSON strings
                mood = state.get("mood")
                if mood:
                    self.state.mood = ATLASMood(json.loads(mood))
                thesis = state.get("market_thesis")
                if thesis:
                    self.state.market_thesis = json.loads(thesis)
                beliefs = state.get("active_beliefs")
                if beliefs:
                    self.state.active_beliefs = json.loads(beliefs)
                lessons = state.get("lessons_learned")
                if lessons:
                    self.state.lessons_learned = json.loads(lessons)
                risk = state.get("risk_appetite")
                if risk:
                    self.state.risk_appetite = json.loads(risk)
                logger.info("Loaded ATLAS state from database")
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")

        try:
            trades = load_all_trades(self.config.db_path)
            self.trade_history = trades
            logger.info(f"Loaded {len(self.trade_history)} historical trades")
        except Exception as e:
            logger.warning(f"Failed to load trade history: {e}")
    
    def _save_state(self):
        """Save state to SQLite"""
        try:
            state = self.state.to_dict()
            for k, v in state.items():
                set_state(self.config.db_path, k, json.dumps(v))
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    # ══════════════════════════════════════════════════════════════════════════
    # MAIN SYSTEM LIFECYCLE
    # ══════════════════════════════════════════════════════════════════════════
    
    async def start(self):
        """Start the ATLAS production system"""
        
        if self.is_running:
            logger.warning("ATLAS is already running")
            return
        
        self.is_running = True
        logger.info("🚀 ATLAS STARTING...")
        
        # Verify connections
        await self._verify_connections()
        
        # Start the monitoring engine
        await self.monitor.start()
        
        # Start the scheduler
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        
        # Run initial scan if market is open
        if await self.alpaca.is_market_open():
            logger.info("Market is open - running initial scan...")
            await self.run_daily_cycle()
        
        logger.info("✓ ATLAS IS RUNNING")
        self._announce()
    
    async def stop(self):
        """Stop the ATLAS production system"""
        
        logger.info("🛑 ATLAS STOPPING...")
        
        self.is_running = False
        
        # Stop scheduler
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        
        # Stop monitoring
        await self.monitor.stop()
        
        # Save state
        self._save_state()
        
        # Close connections
        await self.alpaca.close()
        await self.financial.close()
        
        logger.info("✓ ATLAS STOPPED")
    
    async def _verify_connections(self):
        """Verify all API connections"""
        
        # Test Alpaca
        account = await self.alpaca.get_account()
        if account:
            logger.info(f"✓ Alpaca connected - Account: {account.account_number}")
            logger.info(f"  Equity: ${account.equity:,.2f}")
            logger.info(f"  Buying Power: ${account.buying_power:,.2f}")
        else:
            raise ConnectionError("Failed to connect to Alpaca")
        
        # Test market hours
        hours = await self.alpaca.get_market_hours()
        logger.info(f"  Market Open: {hours['is_open']}")
        
        logger.info("✓ All connections verified")
    
    def _announce(self):
        """ATLAS announces itself"""
        print("\n" + "=" * 60)
        print(ATLASPersonality.PHILOSOPHY)
        print("=" * 60 + "\n")
    
    # ══════════════════════════════════════════════════════════════════════════
    # SCHEDULER
    # ══════════════════════════════════════════════════════════════════════════
    
    async def _scheduler_loop(self):
        """Main scheduler loop - runs daily cycles and entry windows"""
        
        logger.info("Scheduler started")
        
        while self.is_running:
            try:
                now = self.clock.now()
                
                # Check if it's time for daily scan (9:00 AM)
                scan_time = self.clock.parse_hhmm(self.config.daily_scan_time)
                if now.time().hour == scan_time.hour and now.time().minute == scan_time.minute:
                    if await self.alpaca.is_market_open():
                        logger.info("⏰ Daily scan time - running cycle...")
                        await self.run_daily_cycle()
                        # Wait a minute to avoid re-triggering
                        await asyncio.sleep(60)
                        continue
                
                # Check if it's entry window (3:00 PM - 3:45 PM)
                entry_start = self.clock.parse_hhmm(self.config.entry_window_start)
                entry_end = self.clock.parse_hhmm(self.config.entry_window_end)
                
                if entry_start <= now.time() <= entry_end:
                    if await self.alpaca.is_market_open():
                        await self._process_entry_window()
                
                # Sleep for 1 minute before next check
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                await asyncio.sleep(60)
    
    # ══════════════════════════════════════════════════════════════════════════
    # DAILY TRADING CYCLE
    # ══════════════════════════════════════════════════════════════════════════
    
    async def run_daily_cycle(self) -> List[Dict]:
        """
        ATLAS's daily trading cycle.
        
        The cognitive loop:
        1. PERCEIVE - Scan for opportunities
        2. ANALYZE - Deep dive on candidates
        3. REASON - Monte Carlo simulation
        4. DECIDE - Select trades
        5. PLAN - Structure positions
        """
        
        logger.info("=" * 60)
        logger.info("ATLAS DAILY CYCLE - STARTING")
        logger.info(f"Mood: {self.state.mood.value}")
        logger.info(f"Risk Appetite: {self.state.risk_appetite:.2f}")
        logger.info("=" * 60)
        
        # Reset daily counters
        today = self.clock.today()
        if today != getattr(self, '_last_trading_date', None):
            self.today_trades = 0
            self._last_trading_date = today

        if self._daily_pnl_date != today:
            self.daily_realized_pnl = 0.0
            self.consecutive_losses = 0
            self.trading_halted_today = False
            self._daily_pnl_date = today
        
        # Check daily trade limit or circuit breaker
        if self.trading_halted_today:
            logger.warning("Trading halted for today due to risk limits")
            return []

        # Check daily trade limit
        if self.today_trades >= self.config.max_daily_trades:
            logger.info("Daily trade limit reached - no new trades today")
            return []

        # Initialize daily metrics
        self._daily_metrics = {
            "opportunities": 0,
            "excluded_low_confidence": 0,
            "candidates": 0,
            "selected": 0,
            "planned": 0,
            "executed": self.today_trades,
            "brain_failures": 0,
            "brain_blocked_count": 0
        }

        # Step 1: PERCEIVE
        logger.info("\n📡 STEP 1: PERCEIVE - Scanning for opportunities...")
        opportunities = await self._scan_opportunities()
        logger.info(f"Found {len(opportunities)} potential opportunities")
        
        if not opportunities:
            logger.info("No opportunities found today")
            return []
        
        # Step 2: ANALYZE
        logger.info("\n🔬 STEP 2: ANALYZE - Deep analysis of candidates...")
        candidates = await self._analyze_candidates(opportunities)
        logger.info(f"Analyzed {len(candidates)} candidates")
        
        # Step 3: REASON
        logger.info("\n🧠 STEP 3: REASON - Monte Carlo simulation...")
        reasoned = await self._reason_about_candidates(candidates)
        
        # Step 4: DECIDE
        logger.info("\n⚖️ STEP 4: DECIDE - Making trading decisions...")
        selected = await self._make_decisions(reasoned)
        logger.info(f"Selected {len(selected)} trades")
        
        # Step 5: PLAN
        logger.info("\n📋 STEP 5: PLAN - Structuring positions...")
        planned = await self._plan_trades(selected)
        if hasattr(self, "_daily_metrics"):
            self._daily_metrics["planned"] = len(planned)
        
        # Print summary
        self._print_daily_summary(planned)

        # Queue for entry window execution
        self.pending_trades = planned

        # Daily summary log
        if hasattr(self, "_daily_metrics"):
            logger.info(
                "Daily metrics: opportunities=%s, candidates=%s, excluded_low_conf=%s, "
                "selected=%s, planned=%s, executed=%s, brain_failures=%s, brain_blocked=%s",
                self._daily_metrics.get("opportunities"),
                self._daily_metrics.get("candidates"),
                self._daily_metrics.get("excluded_low_confidence"),
                self._daily_metrics.get("selected"),
                self._daily_metrics.get("planned"),
                self._daily_metrics.get("executed"),
                self._daily_metrics.get("brain_failures"),
                self._daily_metrics.get("brain_blocked_count")
            )
        
        # Save state
        self._save_state()
        
        return planned
    
    async def _scan_opportunities(self) -> List[Dict]:
        """Scan for trading opportunities"""
        
        opportunities = []
        
        # 1. Get upcoming earnings (7 days ahead)
        earnings = await self.financial.get_upcoming_earnings(days_ahead=7, include_low_confidence=False)
        
        for earning in earnings:
            if earning.confidence == "low":
                if hasattr(self, "_daily_metrics"):
                    self._daily_metrics["excluded_low_confidence"] += 1
                continue
            # Only include symbols in our watchlist
            if earning.symbol in self.config.watchlist:
                opportunities.append({
                    "type": "earnings",
                    "symbol": earning.symbol,
                    "event_date": earning.earnings_date,
                    "event_time": earning.earnings_time,
                    "data": earning
                })
        
        earnings_count = len([o for o in opportunities if o['type'] == 'earnings'])
        logger.info(f"  Found {earnings_count} earnings events")
        
        # 2. Get upcoming macro events
        macro_events = await self.financial.get_macro_events(days_ahead=7)
        
        for event in macro_events:
            if event.importance == "high":
                opportunities.append({
                    "type": "macro",
                    "symbol": "SPY",  # Default to SPY for macro
                    "event_date": event.event_date,
                    "event_time": event.event_time,
                    "data": event
                })
        
        macro_count = len([o for o in opportunities if o['type'] == 'macro'])
        logger.info(f"  Found {macro_count} macro events")
        if hasattr(self, "_daily_metrics"):
            self._daily_metrics["opportunities"] = len(opportunities)
        
        return opportunities
    
    async def _analyze_candidates(self, opportunities: List[Dict]) -> List[Dict]:
        """Deep analysis of each opportunity"""
        
        candidates = []
        
        for opp in opportunities[:10]:  # Limit to top 10
            symbol = opp["symbol"]
            logger.info(f"  Analyzing {symbol}...")
            
            try:
                # Get company profile
                profile = None
                try:
                    profile = await self.financial.get_company_profile(symbol)
                except Exception as e:
                    logger.debug(f"  Profile fetch failed for {symbol}: {e}")

                # Get earnings history
                history = []
                try:
                    history = await self.financial.get_earnings_history(symbol)
                except Exception as e:
                    logger.debug(f"  Earnings history failed for {symbol}: {e}")

                # Assess tradability
                tradability = {}
                try:
                    tradability = await self.financial.assess_tradability(symbol)
                except Exception as e:
                    logger.debug(f"  Tradability failed for {symbol}: {e}")

                # Get news summary for deep analysis
                news_summary_text = ""
                try:
                    news = await self.financial.check_news(symbol)
                    news_summary_text = news.get("news_summary", "") if isinstance(news, dict) else ""
                except Exception as e:
                    logger.debug(f"  News fetch failed for {symbol}: {e}")

                analysis = {"sentiment_score": 0.0, "risk_flags": ["nvidia_call_failed"]}
                try:
                    analysis = await asyncio.wait_for(
                        asyncio.to_thread(
                            self.brain.analyze_sentiment_and_risks,
                            news_summary_text
                        ),
                        timeout=self.config.brain_timeout_seconds
                    )
                except (asyncio.TimeoutError, Exception) as e:
                    logger.debug(f"  NvidiaBrain failed for {symbol}: {e}")
                    analysis = {"sentiment_score": 0.0, "risk_flags": ["nvidia_call_failed"]}

                if hasattr(self, "_daily_metrics"):
                    risk_flags = analysis.get("risk_flags", []) if isinstance(analysis, dict) else []
                    if "nvidia_call_failed" in risk_flags or "nvidia_parse_failed" in risk_flags:
                        self._daily_metrics["brain_failures"] += 1

                try:
                    insert_intelligence(
                        self.config.db_path,
                        symbol,
                        json.dumps(analysis),
                        news_summary_text
                    )
                except Exception as e:
                    logger.debug(f"  Failed to persist intelligence for {symbol}: {e}")

                # Get current stock price
                quote = None
                try:
                    quote = await self.alpaca.get_stock_quote(symbol)
                except Exception as e:
                    logger.debug(f"  Quote failed for {symbol}: {e}")

                # Calculate historical moves
                historical_moves = []
                if history:
                    historical_moves = [abs(h.stock_move_pct or 0) for h in history if h.stock_move_pct]

                data_source = getattr(opp.get("data"), "source", "unknown")
                data_confidence = getattr(opp.get("data"), "confidence", "medium")
                last_verified = getattr(opp.get("data"), "last_verified", None)

                sector = None
                if profile and getattr(profile, "sector", None):
                    if profile.sector != "Unknown":
                        sector = profile.sector
                if sector is None:
                    sector = self._fallback_sector(symbol)

                candidates.append({
                    **opp,
                    "profile": profile,
                    "sector": sector,
                    "history": history,
                    "deep_analysis": analysis,
                    "tradability": tradability,
                    "current_price": quote.mid if quote else None,
                    "historical_moves": historical_moves,
                    "avg_move": sum(historical_moves) / len(historical_moves) if historical_moves else 3.0,
                    "tradability_score": tradability.get("tradability_score", 50) if isinstance(tradability, dict) else 50,
                    "data_source": data_source,
                    "data_confidence": data_confidence,
                    "last_verified": last_verified,
                    "validation": {
                        "data_source": data_source,
                        "data_confidence": data_confidence,
                        "last_verified": last_verified.isoformat() if last_verified else None
                    }
                })

            except Exception as e:
                logger.warning(f"  Failed to analyze {symbol}: {e}")
                continue
        
        if hasattr(self, "_daily_metrics"):
            self._daily_metrics["candidates"] = len(candidates)

        return candidates
    
    async def _reason_about_candidates(self, candidates: List[Dict]) -> List[Dict]:
        """Apply Monte Carlo reasoning to each candidate"""
        
        reasoned = []
        
        for candidate in candidates:
            symbol = candidate["symbol"]
            
            # Get historical moves or use defaults
            historical_moves = candidate.get("historical_moves", [])
            if not historical_moves:
                historical_moves = [3.0, 2.5, 3.5, 2.0, 4.0, 3.0, 2.5, 3.5]  # Default
            
            # Compute historical statistics
            historical_avg = sum(historical_moves) / len(historical_moves)
            historical_max = max(historical_moves)
            historical_median = sorted(historical_moves)[len(historical_moves) // 2]
            
            # Get current options chain for IV
            current_price = candidate.get("current_price", 100)
            
            if current_price:
                try:
                    # Find the next Friday expiration (typical weeklies)
                    event_date = candidate.get("event_date", date.today() + timedelta(days=1))
                    expiration = self._find_expiration_after(event_date)
                    
                    # Get options chain
                    chain = await self.alpaca.get_options_chain(
                        symbol,
                        expiration=expiration,
                        strike_price_gte=current_price * 0.9,
                        strike_price_lte=current_price * 1.1
                    )
                    
                    if chain:
                        # Estimate current IV from ATM options
                        atm_strike = chain.get_atm_strike(expiration)
                        atm_call = chain.get_contract(atm_strike, expiration, OptionType.CALL)
                        
                        if atm_call:
                            iv_raw = atm_call.implied_volatility
                            if iv_raw <= 0:
                                current_iv = candidate.get("avg_move", 3.0) * 1.5
                            elif iv_raw <= 1.5:
                                current_iv = iv_raw * 100
                            else:
                                current_iv = iv_raw
                        else:
                            current_iv = candidate.get("avg_move", 3.0) * 1.5  # Estimate
                    else:
                        current_iv = candidate.get("avg_move", 3.0) * 1.5
                        
                except Exception as e:
                    logger.debug(f"Failed to get IV for {symbol}: {e}")
                    current_iv = candidate.get("avg_move", 3.0) * 1.5
            else:
                current_iv = candidate.get("avg_move", 3.0) * 1.5
            
            # Run Monte Carlo simulation
            company_stability = 0.5
            profile = candidate.get("profile")
            if profile and getattr(profile, "earnings_predictability_score", None) is not None:
                company_stability = min(1.0, max(0.0, profile.earnings_predictability_score))

            mc_result = self.monte_carlo.simulate_earnings_move(
                historical_avg=historical_avg,
                historical_max=historical_max,
                historical_median=historical_median,
                current_iv=current_iv,
                company_stability=company_stability
            )

            # Calculate edge
            expected_move = mc_result.get("percentile_68", candidate.get("avg_move", 3.0))
            edge = current_iv - expected_move
            
            # ATLAS's confidence
            tradability = candidate.get("tradability_score", 50)
            move_consistency = 1 / (1 + mc_result.get("std_dev", 1.0))
            
            confidence = min(0.95, (tradability / 100 * 0.4 + move_consistency * 0.4 + (0.2 if edge > 1.5 else 0.1)))
            
            candidate.update({
                "monte_carlo": mc_result,
                "current_iv": current_iv,
                "expected_move": expected_move,
                "edge": edge,
                "confidence": confidence
            })
            
            logger.info(f"  {symbol}: IV={current_iv:.1f}%, Expected={expected_move:.1f}%, Edge={edge:.1f}%, Conf={confidence:.0%}")
            
            reasoned.append(candidate)
        
        return reasoned
    
    async def _make_decisions(self, candidates: List[Dict]) -> List[Dict]:
        """ATLAS makes autonomous trading decisions"""
        
        selected = []
        remaining_slots = self.config.max_daily_trades - self.today_trades
        remaining_slots = min(remaining_slots, self.config.max_concurrent_trades - len(self.monitor.positions))
        
        if remaining_slots <= 0:
            logger.info("  No available trading slots")
            return []
        
        # Sort by edge * confidence (best opportunities first)
        ranked = sorted(
            candidates,
            key=lambda x: x.get("edge", 0) * x.get("confidence", 0),
            reverse=True
        )
        
        for candidate in ranked:
            if len(selected) >= remaining_slots:
                break
            
            symbol = candidate["symbol"]
            edge = candidate.get("edge", 0)
            confidence = candidate.get("confidence", 0)
            tradability = candidate.get("tradability_score", 0)
            data_confidence = candidate.get("data_confidence", "medium")
            sector = candidate.get("sector")
            history = candidate.get("history")
            
            # ATLAS's decision criteria
            decision = "PASS"
            reason = ""
            
            # Contextualize before final approval
            context = None
            if self.context_engine:
                try:
                    context = await self.context_engine.analyze(
                        symbol=symbol,
                        sector=sector,
                        historical_earnings=history
                    )
                    candidate["context"] = {
                        "peer_alignment": context.peer_alignment,
                        "sector_trend": context.sector_trend.value,
                        "sentiment_regime": context.sentiment_regime.value,
                        "final_confidence_modifier": context.final_confidence_modifier
                    }
                    # Negative context reduces confidence/edge or rejects trade
                    if context.final_confidence_modifier < 0:
                        confidence = max(0.0, confidence + context.final_confidence_modifier)
                        edge = edge * (1 + context.final_confidence_modifier)
                    if context.peer_alignment < -0.3:
                        decision = "PASS"
                        reason = "Peer alignment contradicts thesis"
                except Exception as e:
                    logger.debug(f"Context analysis failed for {symbol}: {e}")

            # NVIDIA Brain gating
            deep_analysis = candidate.get("deep_analysis", {})
            try:
                risk_flags = deep_analysis.get("risk_flags", [])
                if not isinstance(risk_flags, list):
                    risk_flags = []

                if deep_analysis.get("sentiment_score", 0) < -0.6:
                    decision = "PASS"
                    reason = "NVIDIA Brain detected high negative sentiment"
                if "accounting_issue" in risk_flags:
                    decision = "PASS"
                    reason = "NVIDIA Brain flagged accounting risk"

                # Fail policy for unavailable brain output.
                brain_unavailable = "nvidia_call_failed" in risk_flags or "nvidia_parse_failed" in risk_flags
                if brain_unavailable:
                    if self.config.brain_fail_mode == "block":
                        decision = "PASS"
                        reason = "NVIDIA Brain unavailable (fail-closed policy)"
                        if hasattr(self, "_daily_metrics"):
                            self._daily_metrics["brain_blocked_count"] += 1
                    elif self.config.brain_fail_mode == "warn":
                        confidence = max(0.0, confidence - self.config.brain_warn_confidence_penalty)
                    # allow => no extra action
            except Exception:
                pass

            if decision == "PASS" and reason:
                pass
            elif data_confidence == "low":
                reason = "Low confidence in event data"
            elif edge < self.config.min_edge_threshold:
                reason = f"Edge {edge:.1f}% below threshold {self.config.min_edge_threshold}%"
            elif confidence < self.config.min_confidence:
                reason = f"Confidence {confidence:.0%} below threshold {self.config.min_confidence:.0%}"
            elif tradability < 50:
                reason = f"Tradability {tradability} too low"
            else:
                # Check for red flags
                profile = candidate.get("profile")
                if profile:
                    sector_name = profile.sector if profile.sector else ""
                    if any(word in sector_name.lower() for word in ["biotech", "crypto", "meme"]):
                        reason = f"Sector {sector_name} too volatile"
                    else:
                        decision = "TRADE"
                else:
                    decision = "TRADE"
            
            logger.info(f"  {symbol}: {decision} - {reason if reason else 'Criteria met'}")
            
            if decision == "TRADE":
                # persist adjusted edge/confidence if context modified
                candidate["edge"] = edge
                candidate["confidence"] = confidence
                candidate["decision"] = decision
                selected.append(candidate)
        
        if hasattr(self, "_daily_metrics"):
            self._daily_metrics["selected"] = len(selected)

        return selected
    
    async def _plan_trades(self, selected: List[Dict]) -> List[Dict]:
        """Structure the selected trades as Iron Condors"""
        
        planned = []
        
        for trade in selected:
            symbol = trade["symbol"]
            current_price = trade.get("current_price", 100)
            
            if not current_price:
                continue
            
            # Find expiration
            event_date = trade.get("event_date", date.today() + timedelta(days=1))
            expiration = self._find_expiration_after(event_date)
            
            # Calculate strikes based on Monte Carlo
            mc = trade.get("monte_carlo", {})
            p68 = mc.get("percentile_68", 3.0) / 100  # Convert to decimal
            
            # Short strikes at 68th percentile + buffer
            confidence = trade.get("confidence", 0.6)
            buffer = 0.5 * (1 - confidence)  # More buffer if less confident
            
            short_put_strike = round(current_price * (1 - p68 - buffer), 0)
            short_call_strike = round(current_price * (1 + p68 + buffer), 0)
            
            # Wing width based on price level
            if current_price < 50:
                wing_width = 2.5
            elif current_price < 100:
                wing_width = 5.0
            elif current_price < 300:
                wing_width = 7.5
            else:
                wing_width = 10.0
            
            long_put_strike = short_put_strike - wing_width
            long_call_strike = short_call_strike + wing_width
            
            # Get current pricing
            try:
                pricing = await self.pricer.price_iron_condor(
                    symbol,
                    expiration,
                    long_put_strike,
                    short_put_strike,
                    short_call_strike,
                    long_call_strike
                )
                
                if "error" not in pricing:
                    credit = pricing["pricing"]["mid"]
                    wing_width = long_call_strike - short_call_strike
                    collateral_per_contract = max(0.0, (wing_width - credit)) * 100
                    
                    if collateral_per_contract <= 0:
                        logger.info(f"  {symbol}: Invalid collateral (credit >= width)")
                        continue

                    credit_to_width = credit / wing_width if wing_width > 0 else 0
                    if credit_to_width < self.config.min_credit_to_width:
                        logger.info(f"  {symbol}: Credit/width {credit_to_width:.2f} below minimum")
                        continue
                    
                    # Calculate position size using account limits
                    max_contracts_account = self.account.get_max_contracts(
                        wing_width, confidence, self.state.mood, credit_received=credit
                    )
                    max_contracts_risk = int(self.config.max_risk_per_trade / collateral_per_contract)

                    # Portfolio caps
                    open_collateral = self._get_open_collateral()
                    symbol_collateral = self._get_symbol_collateral(symbol)
                    remaining_total = max(0.0, self.config.max_total_collateral - open_collateral)
                    remaining_symbol = max(0.0, self.config.max_symbol_collateral - symbol_collateral)
                    max_contracts_total = int(remaining_total / collateral_per_contract)
                    max_contracts_symbol = int(remaining_symbol / collateral_per_contract)

                    max_contracts = min(
                        max_contracts_account,
                        max_contracts_risk,
                        max_contracts_total,
                        max_contracts_symbol
                    )
                    
                    if max_contracts <= 0:
                        logger.info(f"  {symbol}: Collateral caps prevent new position")
                        continue
                    
                    # Adjust by confidence and mood
                    mood_mult = ATLASPersonality.get_risk_multiplier(self.state.mood)
                    conf_mult = 0.7 + confidence * 0.3
                    contracts = int(max_contracts * mood_mult * conf_mult)
                    # Context modifier (reduce size if negative)
                    context = trade.get("context", {})
                    modifier = context.get("final_confidence_modifier", 0.0)
                    if modifier < 0:
                        contracts = int(contracts * (1 + modifier))
                    if contracts <= 0:
                        logger.info(f"  {symbol}: Zero contracts after sizing")
                        continue
                    
                    trade["structure"] = {
                        "expiration": expiration.isoformat(),
                        "put_long_strike": long_put_strike,
                        "put_short_strike": short_put_strike,
                        "call_short_strike": short_call_strike,
                        "call_long_strike": long_call_strike,
                        "contracts": contracts,
                        "credit_per_contract": credit,
                        "total_credit": credit * 100 * contracts,
                        "max_loss": collateral_per_contract * contracts,
                        "collateral_required": collateral_per_contract * contracts,
                        "credit_to_width": round(credit_to_width, 3)
                    }
                    
                    planned.append(trade)
                    logger.info(f"  {symbol}: {contracts} contracts @ ${credit:.2f} credit")
                    
            except Exception as e:
                logger.error(f"  Failed to price {symbol}: {e}")
                continue
        
        return planned
    
    def _find_expiration_after(self, event_date: date) -> date:
        """Find the first Friday expiration after an event date"""
        
        if isinstance(event_date, datetime):
            event_date = event_date.date()
        
        # Find next Friday
        days_until_friday = (4 - event_date.weekday()) % 7
        if days_until_friday == 0:
            days_until_friday = 7
        
        return event_date + timedelta(days=days_until_friday)
    
    def _print_daily_summary(self, planned: List[Dict]):
        """Print summary of planned trades"""
        
        print("\n" + "=" * 60)
        print("ATLAS DAILY SUMMARY")
        print("=" * 60)
        print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"Mood: {self.state.mood.value}")
        print(f"Trades Planned: {len(planned)}")
        print("-" * 60)
        
        total_credit = 0
        total_risk = 0
        
        for trade in planned:
            symbol = trade["symbol"]
            structure = trade.get("structure", {})
            
            print(f"\n{symbol} Iron Condor:")
            print(f"  Event: {trade.get('type', 'unknown')} on {trade.get('event_date')}")
            print(f"  Strikes: {structure.get('put_long_strike')}/{structure.get('put_short_strike')} P | {structure.get('call_short_strike')}/{structure.get('call_long_strike')} C")
            print(f"  Contracts: {structure.get('contracts')}")
            print(f"  Credit: ${structure.get('total_credit', 0):.2f}")
            print(f"  Max Loss: ${structure.get('max_loss', 0):.2f}")
            print(f"  Edge: {trade.get('edge', 0):.1f}% | Confidence: {trade.get('confidence', 0):.0%}")
            
            total_credit += structure.get('total_credit', 0)
            total_risk += structure.get('max_loss', 0)
        
        print("-" * 60)
        print(f"TOTAL CREDIT: ${total_credit:.2f}")
        print(f"TOTAL RISK: ${total_risk:.2f}")
        print("=" * 60 + "\n")
    
    # ══════════════════════════════════════════════════════════════════════════
    # ENTRY WINDOW PROCESSING
    # ══════════════════════════════════════════════════════════════════════════
    
    async def _process_entry_window(self):
        """Process pending trades during the entry window"""
        logger.debug("Entry window check...")

        if self.trading_halted_today:
            logger.warning("Entry window skipped - trading halted for today")
            return

        if not self.pending_trades:
            return

        executed = 0
        remaining = []

        for trade in list(self.pending_trades):
            if self.today_trades >= self.config.max_daily_trades:
                remaining.append(trade)
                continue

            if len(self.monitor.positions) >= self.config.max_concurrent_trades:
                remaining.append(trade)
                continue

            ok, reason = await self._validate_trade_for_entry(trade)
            if not ok:
                logger.info(f"Skipping {trade.get('symbol')} entry: {reason}")
                continue

            order_id = await self.execute_trade(trade)
            if order_id:
                executed += 1
            else:
                remaining.append(trade)

        self.pending_trades = remaining

        if hasattr(self, "_daily_metrics"):
            self._daily_metrics["executed"] = self.today_trades

        if executed:
            logger.info(f"Entry window executed {executed} trades")

    async def _validate_trade_for_entry(self, trade: Dict) -> Tuple[bool, str]:
        """Re-validate liquidity and pricing before entry"""
        structure = trade.get("structure")
        if not structure:
            return False, "missing_structure"

        # Ensure event hasn't passed
        event_date = trade.get("event_date")
        event_time = str(trade.get("event_time", "")).upper()
        now = self.clock.now()

        if isinstance(event_date, datetime):
            event_date = event_date.date()

        if event_date and event_date < now.date():
            return False, "event_passed"
        if event_date and event_date == now.date():
            if event_time == "BMO" and now.time() >= time(9, 30):
                return False, "event_passed_bmo"
            if re.match(r"^\d{2}:\d{2}$", event_time):
                try:
                    evt_t = datetime.strptime(event_time, "%H:%M").time()
                    if now.time() >= evt_t:
                        return False, "event_passed_intraday"
                except Exception:
                    pass

        expiration = date.fromisoformat(structure["expiration"])
        chain = await self.alpaca.get_options_chain(
            trade["symbol"],
            expiration=expiration,
            strike_price_gte=structure["put_long_strike"] - 5,
            strike_price_lte=structure["call_long_strike"] + 5
        )
        if not chain:
            return False, "no_chain"

        put_short = chain.get_contract(structure["put_short_strike"], expiration, OptionType.PUT)
        call_short = chain.get_contract(structure["call_short_strike"], expiration, OptionType.CALL)
        if not put_short or not call_short:
            return False, "missing_short_legs"

        if put_short.open_interest < self.config.min_open_interest or call_short.open_interest < self.config.min_open_interest:
            return False, "open_interest_low"
        if put_short.volume < self.config.min_volume or call_short.volume < self.config.min_volume:
            return False, "volume_low"

        if put_short.spread_percent > self.config.max_spread_pct or call_short.spread_percent > self.config.max_spread_pct:
            return False, "spread_too_wide"

        wing_width = structure["call_long_strike"] - structure["call_short_strike"]
        credit = structure["credit_per_contract"]
        credit_to_width = credit / wing_width if wing_width > 0 else 0
        if credit_to_width < self.config.min_credit_to_width:
            return False, "credit_to_width_low"

        return True, "ok"

    def _get_open_collateral(self) -> float:
        total = 0.0
        for pos in self.monitor.positions.values():
            if pos.status in {"open", "closing"}:
                total += pos.max_loss
        return total

    def _fallback_sector(self, symbol: str) -> Optional[str]:
        """Fallback sector mapping when profile is unavailable"""
        sector_map = {
            # Consumer Staples
            "PEP": "Consumer Staples",
            "KO": "Consumer Staples",
            "PG": "Consumer Staples",
            "CL": "Consumer Staples",
            "KHC": "Consumer Staples",
            "GIS": "Consumer Staples",
            "K": "Consumer Staples",
            "CAG": "Consumer Staples",
            # Healthcare / Pharma
            "MRK": "Health Care",
            "PFE": "Health Care",
            "BMY": "Health Care",
            "ABBV": "Health Care",
            "LLY": "Health Care",
            "JNJ": "Health Care",
            "UNH": "Health Care",
            "CI": "Health Care",
            "CVS": "Health Care",
            "HUM": "Health Care",
            "ELV": "Health Care",
            # Financials
            "CME": "Financials",
            "ICE": "Financials",
            "CBOE": "Financials",
            "NDAQ": "Financials",
            "MSCI": "Financials",
            # Industrials
            "LIN": "Materials",
            "APD": "Materials",
            "RTX": "Industrials",
            "LMT": "Industrials",
            "NOC": "Industrials",
            "GD": "Industrials",
            # Utilities
            "NEE": "Utilities",
            "DUK": "Utilities",
            "SO": "Utilities",
            "D": "Utilities",
            # Communication Services / Telecom
            "VZ": "Communication Services",
            "T": "Communication Services",
            # Indices / ETFs
            "SPY": "Financials",
            "QQQ": "Technology",
            "IWM": "Financials"
        }
        return sector_map.get(symbol)

    def _get_symbol_collateral(self, symbol: str) -> float:
        total = 0.0
        for pos in self.monitor.positions.values():
            if pos.status in {"open", "closing"} and pos.symbol == symbol:
                total += pos.max_loss
        return total
    
    async def execute_trade(self, trade: Dict) -> Optional[str]:
        """Execute a planned trade"""
        
        structure = trade.get("structure")
        if not structure:
            logger.error("No trade structure to execute")
            return None
        
        # Build the Iron Condor order
        ic_order = IronCondorOrder(
            underlying=trade["symbol"],
            expiration=date.fromisoformat(structure["expiration"]),
            put_long_strike=structure["put_long_strike"],
            put_short_strike=structure["put_short_strike"],
            call_short_strike=structure["call_short_strike"],
            call_long_strike=structure["call_long_strike"],
            contracts=structure["contracts"],
            limit_price=structure["credit_per_contract"]
        )
        
        # Submit to Alpaca
        order_id = await self.alpaca.submit_iron_condor(ic_order)
        
        if order_id:
            filled = await self._wait_for_order_fill(order_id)
            if not filled:
                await self.alpaca.cancel_order(order_id)
                # Reprice once with lower credit to improve fill
                ic_order.limit_price = max(0.01, ic_order.limit_price - 0.05)
                order_id = await self.alpaca.submit_iron_condor(ic_order)
                if not order_id or not await self._wait_for_order_fill(order_id):
                    if order_id:
                        await self.alpaca.cancel_order(order_id)
                    logger.error(f"✗ Trade execution failed (no fill): {trade['symbol']}")
                    return None

            order_details = await self.alpaca.get_order(order_id)
            entry_credit = structure["credit_per_contract"]
            if order_details and order_details.filled_avg_price:
                entry_credit = order_details.filled_avg_price

            logger.info(f"✓ Trade executed: {trade['symbol']} - Order ID: {order_id}")
            
            # Add to monitoring
            position = MonitoredPosition(
                position_id=order_id,
                symbol=trade["symbol"],
                put_long_strike=structure["put_long_strike"],
                put_short_strike=structure["put_short_strike"],
                call_short_strike=structure["call_short_strike"],
                call_long_strike=structure["call_long_strike"],
                expiration=date.fromisoformat(structure["expiration"]),
                contracts=structure["contracts"],
                entry_credit=entry_credit,
                entry_time=datetime.now(),
                entry_underlying_price=trade.get("current_price", 0),
                event_date=trade.get("event_date"),
                event_time=trade.get("event_time")
            )
            
            self.monitor.add_position(position)
            self.today_trades += 1
            
            # Record in history
            trade_id = insert_trade(
                self.config.db_path,
                trade["symbol"],
                entry_credit,
                structure["contracts"],
                outcome=None
            )
            self.trade_history.append({
                "id": trade_id,
                "order_id": order_id,
                "symbol": trade["symbol"],
                "structure": structure,
                "entry_time": datetime.now().isoformat(),
                "edge": trade.get("edge"),
                "confidence": trade.get("confidence"),
                "data_source": trade.get("data_source"),
                "data_confidence": trade.get("data_confidence"),
                "current_iv": trade.get("current_iv"),
                "expected_move": trade.get("expected_move"),
                "validation": trade.get("validation", {})
            })
            
            self._save_state()
            
            return order_id
        else:
            logger.error(f"✗ Trade execution failed: {trade['symbol']}")
            return None

    async def _wait_for_order_fill(self, order_id: str, timeout_seconds: int = 120) -> bool:
        """Poll order status until filled or timeout"""
        start = datetime.now()
        while (datetime.now() - start).total_seconds() < timeout_seconds:
            order = await self.alpaca.get_order(order_id)
            if order and order.status == "filled":
                return True
            await asyncio.sleep(5)
        return False
    
    # ══════════════════════════════════════════════════════════════════════════
    # CALLBACKS
    # ══════════════════════════════════════════════════════════════════════════
    
    def _handle_alert(self, alert: Alert):
        """Handle alerts from the monitoring engine"""
        
        # Log based on level
        if alert.level == AlertLevel.CRITICAL:
            logger.critical(f"🚨 {alert.symbol}: {alert.message}")
        elif alert.level == AlertLevel.WARNING:
            logger.warning(f"⚠️ {alert.symbol}: {alert.message}")
        elif alert.level == AlertLevel.ACTION_REQUIRED:
            logger.warning(f"📢 {alert.symbol}: {alert.message}")
        else:
            logger.info(f"ℹ️ {alert.symbol}: {alert.message}")
        
        # Could add webhook/notification here
    
    def _handle_exit_signal(self, position: MonitoredPosition, reason: ExitReason):
        """Handle exit signals from the monitoring engine"""
        
        logger.info(f"🚪 EXIT SIGNAL: {position.symbol} - {reason.value}")
        
        # Record the exit
        for hist in self.trade_history:
            if hist.get("order_id") == position.position_id:
                hist["exit_time"] = datetime.now().isoformat()
                hist["exit_reason"] = reason.value
                hist["realized_pnl"] = position.unrealized_pnl
                trade_id = hist.get("id")
                if trade_id:
                    update_trade_outcome(self.config.db_path, int(trade_id), reason.value)
                break
        
        self._save_state()
        
        # Update ATLAS's beliefs based on outcome
        self._learn_from_trade(position, reason)

        # Update risk controls
        today = self.clock.today()
        if self._daily_pnl_date != today:
            self.daily_realized_pnl = 0.0
            self.consecutive_losses = 0
            self.trading_halted_today = False
            self._daily_pnl_date = today

        pnl = position.unrealized_pnl
        self.daily_realized_pnl += pnl
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        daily_loss_limit = self.config.total_capital * self.config.daily_loss_limit_pct
        if self.consecutive_losses >= self.config.max_consecutive_losses:
            self.trading_halted_today = True
            logger.warning("Trading halted: max consecutive losses reached")
        if self.daily_realized_pnl <= -daily_loss_limit:
            self.trading_halted_today = True
            logger.warning("Trading halted: daily loss limit reached")
    
    def _learn_from_trade(self, position: MonitoredPosition, reason: ExitReason):
        """ATLAS learns from each trade outcome"""
        
        symbol = position.symbol
        pnl = position.unrealized_pnl
        pnl_pct = position.unrealized_pnl_pct
        
        # Update beliefs about this symbol
        if symbol not in self.state.active_beliefs:
            self.state.active_beliefs[symbol] = 0.5
        
        # Good outcome increases belief, bad outcome decreases
        if pnl > 0:
            self.state.active_beliefs[symbol] = min(1.0, self.state.active_beliefs[symbol] + 0.05)
            lesson = f"{symbol}: Profitable trade ({reason.value}). Pattern worked."
        else:
            self.state.active_beliefs[symbol] = max(0.1, self.state.active_beliefs[symbol] - 0.1)
            lesson = f"{symbol}: Loss ({reason.value}). Review what went wrong."
        
        self.state.lessons_learned.append(lesson)
        
        # Update mood based on recent outcomes
        recent_pnls = [h.get("realized_pnl", 0) for h in self.trade_history[-5:] if "realized_pnl" in h]
        
        if recent_pnls:
            win_rate = sum(1 for p in recent_pnls if p > 0) / len(recent_pnls)
            
            if win_rate >= 0.8:
                self.state.mood = ATLASMood.CONFIDENT
            elif win_rate >= 0.6:
                self.state.mood = ATLASMood.CAUTIOUS
            elif win_rate >= 0.4:
                self.state.mood = ATLASMood.DEFENSIVE
            else:
                self.state.mood = ATLASMood.DEFENSIVE
                self.state.risk_appetite = max(0.2, self.state.risk_appetite - 0.1)
        
        logger.info(f"📚 Learned: {lesson}")
        logger.info(f"📊 Updated mood: {self.state.mood.value}")
    
    # ══════════════════════════════════════════════════════════════════════════
    # STATUS & INTERFACE
    # ══════════════════════════════════════════════════════════════════════════
    
    def get_status(self) -> Dict:
        """Get current system status"""
        
        monitor_status = self.monitor.get_status()
        
        return {
            "system": {
                "is_running": self.is_running,
                "mode": "PAPER" if self.config.paper_trading else "LIVE",
                "uptime": str(datetime.now() - getattr(self, '_start_time', datetime.now()))
            },
            "atlas": {
                "mood": self.state.mood.value,
                "risk_appetite": self.state.risk_appetite,
                "active_beliefs": len(self.state.active_beliefs),
                "lessons_learned": len(self.state.lessons_learned)
            },
            "trading": {
                "today_trades": self.today_trades,
                "total_trades": len(self.trade_history),
                "open_positions": monitor_status["open_positions"],
                "total_pnl": monitor_status["total_unrealized_pnl"]
            },
            "monitoring": {
                "checks_performed": monitor_status["checks_performed"],
                "alerts_generated": monitor_status["alerts_generated"]
            }
        }
    
    def print_status(self):
        """Print current status"""
        
        status = self.get_status()
        
        print("\n" + "=" * 60)
        print("ATLAS SYSTEM STATUS")
        print("=" * 60)
        print(f"Running: {'✓' if status['system']['is_running'] else '✗'}")
        print(f"Mode: {status['system']['mode']}")
        print(f"Mood: {status['atlas']['mood']}")
        print(f"Risk Appetite: {status['atlas']['risk_appetite']:.2f}")
        print("-" * 60)
        print(f"Today's Trades: {status['trading']['today_trades']}")
        print(f"Open Positions: {status['trading']['open_positions']}")
        print(f"Total P/L: ${status['trading']['total_pnl']:,.2f}")
        print("-" * 60)
        print(f"Checks: {status['monitoring']['checks_performed']}")
        print(f"Alerts: {status['monitoring']['alerts_generated']}")
        print("=" * 60 + "\n")
        
        # Print position details
        self.monitor.print_status()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    """Main entry point for ATLAS production system"""
    
    parser = argparse.ArgumentParser(description="ATLAS Production Trading System")
    parser.add_argument("--config", default="atlas_config.json", help="Config file path")
    parser.add_argument("--status", action="store_true", help="Show current status")
    parser.add_argument("--scan", action="store_true", help="Run daily scan only")
    parser.add_argument("--run", action="store_true", help="Run full production system")
    
    args = parser.parse_args()
    
    # Load or create configuration
    if os.path.exists(args.config):
        config = ATLASProductionConfig.from_file(args.config)
    else:
        config = ATLASProductionConfig()
        config.save(args.config)
        logger.info(f"Created default config: {args.config}")
    
    # Validate required environment variables
    if not config.alpaca_api_key:
        print("ERROR: Set ALPACA_API_KEY environment variable")
        print("  export ALPACA_API_KEY='your-key'")
        print("  export ALPACA_API_SECRET='your-secret'")
        print("  export PERPLEXITY_API_KEY='your-key'  (optional but recommended)")
        return
    
    # Initialize ATLAS
    atlas = ATLASProduction(config)
    
    # Handle signals for graceful shutdown
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        logger.info("Received shutdown signal...")
        asyncio.create_task(atlas.stop())
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        if args.status:
            # Just show status
            await atlas._verify_connections()
            atlas.print_status()
            
        elif args.scan:
            # Run single scan
            await atlas._verify_connections()
            trades = await atlas.run_daily_cycle()
            
            if trades:
                print("\nWould you like to execute these trades? (y/n)")
                # In production, this would be automated
                
        elif args.run:
            # Full production mode
            await atlas.start()
            atlas._start_time = datetime.now()
            
            # Keep running until stopped
            while atlas.is_running:
                await asyncio.sleep(1)
        
        else:
            # Default: show help
            parser.print_help()
            
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        await atlas.stop()


if __name__ == "__main__":
    asyncio.run(main())
