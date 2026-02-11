"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                      ATLAS MONITORING ENGINE                                  ║
║              5-Minute Continuous Position & News Monitoring                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

This module provides ATLAS with continuous market awareness:
- Position monitoring every 5 minutes
- Exit condition evaluation
- Breaking news detection
- Risk alerts
- Dynamic position adjustment recommendations

Author: ATLAS Development Team
Version: 1.0.0 - Production Ready
"""

import asyncio
import logging
from datetime import datetime, timedelta, time, date
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
import json
import re
import os

# Import ATLAS components
from atlas_alpaca import AlpacaClient, OptionsChain, Position, IronCondorOrder
from atlas_financial import FinancialDataService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ATLAS.Monitor")

# ══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════

class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    ACTION_REQUIRED = "action_required"

class ExitReason(Enum):
    PROFIT_TARGET = "profit_target"
    STOP_LOSS = "stop_loss"
    STRIKE_BREACH = "strike_breach"
    TIME_DECAY = "time_decay"
    NEWS_EVENT = "news_event"
    MANUAL = "manual"
    EXPIRATION_NEAR = "expiration_near"
    EVENT_NEAR = "event_near"

@dataclass
class MonitoredPosition:
    """A position being monitored by ATLAS"""
    position_id: str
    symbol: str
    
    # Iron Condor details
    put_long_strike: float
    put_short_strike: float
    call_short_strike: float
    call_long_strike: float
    expiration: date
    contracts: int

    # Event metadata (for event-proximity checks)
    event_date: Optional[date] = None
    event_time: Optional[str] = None
    
    # Entry details
    entry_credit: float  # Credit received per contract
    entry_time: datetime
    entry_underlying_price: float
    
    # Current state
    current_value: float = 0.0  # Current position value (cost to close)
    current_underlying_price: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    
    # Monitoring state
    last_check_time: Optional[datetime] = None
    alerts: List[Dict] = field(default_factory=list)
    status: str = "open"
    
    # Exit tracking
    exit_reason: Optional[ExitReason] = None
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    realized_pnl: Optional[float] = None
    
    @property
    def max_profit(self) -> float:
        """Maximum profit = entry credit × 100 × contracts"""
        return self.entry_credit * 100 * self.contracts
    
    @property
    def max_loss(self) -> float:
        """Maximum loss = (wing width - entry credit) × 100 × contracts"""
        put_width = self.put_short_strike - self.put_long_strike
        call_width = self.call_long_strike - self.call_short_strike
        wing_width = max(put_width, call_width)
        return (wing_width - self.entry_credit) * 100 * self.contracts
    
    @property
    def profit_pct_of_max(self) -> float:
        """Current profit as percentage of max profit"""
        if self.max_profit > 0:
            return (self.unrealized_pnl / self.max_profit) * 100
        return 0.0
    
    @property
    def loss_pct_of_max(self) -> float:
        """Current loss as percentage of max loss"""
        if self.unrealized_pnl < 0 and self.max_loss > 0:
            return (abs(self.unrealized_pnl) / self.max_loss) * 100
        return 0.0
    
    @property
    def is_put_side_threatened(self) -> bool:
        """Check if price is threatening the put side"""
        buffer = (self.put_short_strike - self.put_long_strike) * 0.3
        return self.current_underlying_price <= self.put_short_strike + buffer
    
    @property
    def is_call_side_threatened(self) -> bool:
        """Check if price is threatening the call side"""
        buffer = (self.call_long_strike - self.call_short_strike) * 0.3
        return self.current_underlying_price >= self.call_short_strike - buffer
    
    @property
    def days_to_expiration(self) -> int:
        """Days until expiration"""
        return (self.expiration - date.today()).days

@dataclass
class Alert:
    """Monitoring alert"""
    timestamp: datetime
    position_id: str
    symbol: str
    level: AlertLevel
    message: str
    action_recommended: Optional[str] = None
    data: Dict = field(default_factory=dict)

@dataclass 
class MonitoringConfig:
    """Configuration for the monitoring engine"""
    # Timing
    check_interval_seconds: int = 300  # 5 minutes
    news_check_interval_seconds: int = 300  # 5 minutes
    
    # Exit thresholds
    profit_target_pct: float = 50.0  # Close at 50% of max profit
    stop_loss_pct: float = 200.0  # Close at 200% of credit received (100% loss of credit + 100% more)
    max_loss_pct: float = 75.0  # Close at 75% of max theoretical loss
    
    # Strike breach settings
    strike_buffer_pct: float = 30.0  # Alert when within 30% of wing width to short strike
    
    # Time-based settings
    close_hours_before_expiration: int = 3  # Close 3 hours before expiration
    close_hours_before_event: int = 3  # Close 3 hours before known event
    
    # News sensitivity
    news_impact_threshold: str = "medium"  # low, medium, high
    
    # Notification settings
    enable_sound_alerts: bool = True
    enable_push_notifications: bool = False
    notification_webhook_url: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# MONITORING ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class MonitoringEngine:
    """
    ATLAS's eyes that never sleep.
    
    Continuously monitors:
    - Open positions every 5 minutes
    - Breaking news
    - Exit conditions
    - Risk levels
    """
    
    def __init__(
        self,
        alpaca: AlpacaClient,
        financial_service: FinancialDataService,
        config: Optional[MonitoringConfig] = None
    ):
        self.alpaca = alpaca
        self.financial = financial_service
        self.config = config or MonitoringConfig()
        
        # State
        self.positions: Dict[str, MonitoredPosition] = {}
        self.alerts: List[Alert] = []
        self.is_running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._news_task: Optional[asyncio.Task] = None
        
        # Callbacks
        self.on_alert: Optional[Callable[[Alert], None]] = None
        self.on_exit_signal: Optional[Callable[[MonitoredPosition, ExitReason], None]] = None
        
        # Metrics
        self.checks_performed = 0
        self.alerts_generated = 0
        self.positions_closed = 0
        
        logger.info("MonitoringEngine initialized")
        logger.info(f"  Check interval: {self.config.check_interval_seconds}s")
        logger.info(f"  Profit target: {self.config.profit_target_pct}%")
        logger.info(f"  Stop loss: {self.config.max_loss_pct}% of max loss")
    
    # ══════════════════════════════════════════════════════════════════════════
    # POSITION MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════
    
    def add_position(self, position: MonitoredPosition):
        """Add a position to monitor"""
        self.positions[position.position_id] = position
        logger.info(f"Added position to monitor: {position.symbol} ({position.position_id})")
        
        self._generate_alert(
            position.position_id,
            position.symbol,
            AlertLevel.INFO,
            f"Position opened: {position.contracts} contracts @ ${position.entry_credit:.2f} credit",
            data={
                "entry_credit": position.entry_credit,
                "max_profit": position.max_profit,
                "max_loss": position.max_loss
            }
        )
    
    def remove_position(self, position_id: str):
        """Remove a position from monitoring"""
        if position_id in self.positions:
            position = self.positions.pop(position_id)
            logger.info(f"Removed position from monitoring: {position.symbol}")
    
    def get_position(self, position_id: str) -> Optional[MonitoredPosition]:
        """Get a monitored position"""
        return self.positions.get(position_id)
    
    def get_all_positions(self) -> List[MonitoredPosition]:
        """Get all monitored positions"""
        return list(self.positions.values())
    
    # ══════════════════════════════════════════════════════════════════════════
    # MONITORING LOOP
    # ══════════════════════════════════════════════════════════════════════════
    
    async def start(self):
        """Start the monitoring engine"""
        if self.is_running:
            logger.warning("Monitoring engine already running")
            return
        
        self.is_running = True
        logger.info("Starting monitoring engine...")
        
        # Start position monitoring task
        self._monitor_task = asyncio.create_task(self._position_monitoring_loop())
        
        # Start news monitoring task
        self._news_task = asyncio.create_task(self._news_monitoring_loop())
        
        logger.info("Monitoring engine started")
    
    async def stop(self):
        """Stop the monitoring engine"""
        self.is_running = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        if self._news_task:
            self._news_task.cancel()
            try:
                await self._news_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Monitoring engine stopped")
    
    async def _position_monitoring_loop(self):
        """Main position monitoring loop - runs every 5 minutes"""
        logger.info("Position monitoring loop started")
        
        while self.is_running:
            try:
                # Only monitor during market hours
                if await self._is_market_hours():
                    await self._check_all_positions()
                else:
                    logger.debug("Market closed, skipping position check")
                
                # Wait for next interval
                await asyncio.sleep(self.config.check_interval_seconds)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Wait a minute before retrying
    
    async def _news_monitoring_loop(self):
        """News monitoring loop - checks for breaking news every 5 minutes"""
        logger.info("News monitoring loop started")
        
        while self.is_running:
            try:
                # Check news for all positions
                await self._check_news_for_positions()
                
                # Wait for next interval
                await asyncio.sleep(self.config.news_check_interval_seconds)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in news monitoring loop: {e}")
                await asyncio.sleep(60)
    
    async def _is_market_hours(self) -> bool:
        """Check if we're in market hours"""
        try:
            return await self.alpaca.is_market_open()
        except:
            # Fallback: assume 9:30 AM - 4:00 PM ET on weekdays
            now = datetime.now()
            if now.weekday() >= 5:  # Weekend
                return False
            market_open = time(9, 30)
            market_close = time(16, 0)
            return market_open <= now.time() <= market_close
    
    # ══════════════════════════════════════════════════════════════════════════
    # POSITION CHECKING
    # ══════════════════════════════════════════════════════════════════════════
    
    async def _check_all_positions(self):
        """Check all monitored positions"""
        self.checks_performed += 1
        logger.debug(f"Checking {len(self.positions)} positions...")
        
        for position_id, position in list(self.positions.items()):
            if position.status != "open":
                continue
            
            try:
                await self._check_position(position)
            except Exception as e:
                logger.error(f"Error checking position {position_id}: {e}")
    
    async def _check_position(self, position: MonitoredPosition):
        """Check a single position for exit conditions"""
        
        # 1. Get current underlying price
        quote = await self.alpaca.get_stock_quote(position.symbol)
        if not quote:
            logger.warning(f"Failed to get quote for {position.symbol}")
            return
        
        position.current_underlying_price = quote.mid
        position.last_check_time = datetime.now()
        
        # 2. Get current option prices to calculate position value
        await self._update_position_value(position)
        
        # 3. Check all exit conditions
        exit_reason = await self._evaluate_exit_conditions(position)
        
        if exit_reason:
            await self._trigger_exit(position, exit_reason)
    
    async def _update_position_value(self, position: MonitoredPosition):
        """Update the current value of a position"""
        
        try:
            # Get current options chain
            chain = await self.alpaca.get_options_chain(
                position.symbol,
                expiration=position.expiration,
                strike_price_gte=position.put_long_strike - 5,
                strike_price_lte=position.call_long_strike + 5
            )
            
            if not chain:
                return
            
            # Get all four legs
            from atlas_alpaca import OptionType
            
            put_long = chain.get_contract(position.put_long_strike, position.expiration, OptionType.PUT)
            put_short = chain.get_contract(position.put_short_strike, position.expiration, OptionType.PUT)
            call_short = chain.get_contract(position.call_short_strike, position.expiration, OptionType.CALL)
            call_long = chain.get_contract(position.call_long_strike, position.expiration, OptionType.CALL)
            
            if all([put_long, put_short, call_short, call_long]):
                # Calculate cost to close (we'd pay this to buy back)
                # Iron Condor value = value we'd pay to close
                close_cost = (
                    put_short.ask - put_long.bid +
                    call_short.ask - call_long.bid
                )
                
                position.current_value = close_cost
                
                # Calculate P/L
                # We received entry_credit, now it costs close_cost to close
                # P/L per contract = entry_credit - close_cost
                pnl_per_contract = position.entry_credit - close_cost
                position.unrealized_pnl = pnl_per_contract * 100 * position.contracts
                
                if position.max_profit > 0:
                    position.unrealized_pnl_pct = (position.unrealized_pnl / position.max_profit) * 100
                
                logger.debug(
                    f"{position.symbol}: Price ${position.current_underlying_price:.2f}, "
                    f"P/L ${position.unrealized_pnl:.2f} ({position.unrealized_pnl_pct:.1f}% of max)"
                )
        
        except Exception as e:
            logger.error(f"Failed to update position value for {position.symbol}: {e}")
    
    async def _evaluate_exit_conditions(self, position: MonitoredPosition) -> Optional[ExitReason]:
        """Evaluate all exit conditions for a position"""
        
        # 1. PROFIT TARGET - Close at 50% of max profit
        if position.profit_pct_of_max >= self.config.profit_target_pct:
            self._generate_alert(
                position.position_id,
                position.symbol,
                AlertLevel.ACTION_REQUIRED,
                f"🎯 PROFIT TARGET HIT: {position.profit_pct_of_max:.1f}% of max profit",
                action_recommended="CLOSE POSITION",
                data={"pnl": position.unrealized_pnl, "pnl_pct": position.unrealized_pnl_pct}
            )
            return ExitReason.PROFIT_TARGET
        
        # 2. STOP LOSS - Close at 75% of max loss
        if position.loss_pct_of_max >= self.config.max_loss_pct:
            self._generate_alert(
                position.position_id,
                position.symbol,
                AlertLevel.CRITICAL,
                f"🚨 STOP LOSS HIT: {position.loss_pct_of_max:.1f}% of max loss",
                action_recommended="CLOSE POSITION IMMEDIATELY",
                data={"pnl": position.unrealized_pnl, "loss_pct": position.loss_pct_of_max}
            )
            return ExitReason.STOP_LOSS
        
        # 3. STRIKE BREACH - Price near short strikes
        if position.is_put_side_threatened:
            self._generate_alert(
                position.position_id,
                position.symbol,
                AlertLevel.WARNING,
                f"⚠️ PUT SIDE THREATENED: Price ${position.current_underlying_price:.2f} near put strike ${position.put_short_strike}",
                action_recommended="Consider closing put spread or full position",
                data={"price": position.current_underlying_price, "put_short": position.put_short_strike}
            )
            
            # If actually breached
            if position.current_underlying_price <= position.put_short_strike:
                self._generate_alert(
                    position.position_id,
                    position.symbol,
                    AlertLevel.CRITICAL,
                    f"🚨 PUT STRIKE BREACHED: Price ${position.current_underlying_price:.2f} < ${position.put_short_strike}",
                    action_recommended="CLOSE POSITION",
                    data={"price": position.current_underlying_price}
                )
                return ExitReason.STRIKE_BREACH
        
        if position.is_call_side_threatened:
            self._generate_alert(
                position.position_id,
                position.symbol,
                AlertLevel.WARNING,
                f"⚠️ CALL SIDE THREATENED: Price ${position.current_underlying_price:.2f} near call strike ${position.call_short_strike}",
                action_recommended="Consider closing call spread or full position",
                data={"price": position.current_underlying_price, "call_short": position.call_short_strike}
            )
            
            # If actually breached
            if position.current_underlying_price >= position.call_short_strike:
                self._generate_alert(
                    position.position_id,
                    position.symbol,
                    AlertLevel.CRITICAL,
                    f"🚨 CALL STRIKE BREACHED: Price ${position.current_underlying_price:.2f} > ${position.call_short_strike}",
                    action_recommended="CLOSE POSITION",
                    data={"price": position.current_underlying_price}
                )
                return ExitReason.STRIKE_BREACH

        # 4. EVENT PROXIMITY (intraday events only)
        if position.event_date and position.event_time:
            time_str = str(position.event_time).upper()
            if re.match(r"^\d{2}:\d{2}$", time_str):
                try:
                    evt_t = datetime.strptime(time_str, "%H:%M").time()
                    event_dt = datetime.combine(position.event_date, evt_t)
                    now = datetime.now()
                    hours_to_event = (event_dt - now).total_seconds() / 3600
                    if 0 <= hours_to_event <= self.config.close_hours_before_event:
                        self._generate_alert(
                            position.position_id,
                            position.symbol,
                            AlertLevel.ACTION_REQUIRED,
                            f"⏰ EVENT APPROACHING: {hours_to_event:.1f} hours to event",
                            action_recommended="CLOSE POSITION before event",
                            data={"event_time": position.event_time, "event_date": str(position.event_date)}
                        )
                        return ExitReason.EVENT_NEAR
                except Exception:
                    pass
        
        # 5. TIME DECAY - Close before expiration
        hours_to_expiration = position.days_to_expiration * 24
        if hours_to_expiration <= self.config.close_hours_before_expiration:
            self._generate_alert(
                position.position_id,
                position.symbol,
                AlertLevel.ACTION_REQUIRED,
                f"⏰ EXPIRATION APPROACHING: {position.days_to_expiration} days remaining",
                action_recommended="CLOSE POSITION before expiration",
                data={"days_remaining": position.days_to_expiration}
            )
            return ExitReason.EXPIRATION_NEAR
        
        # 5. 50% profit reminder at 30%
        if 30 <= position.profit_pct_of_max < 50:
            if not any(a.get("type") == "profit_reminder" for a in position.alerts):
                self._generate_alert(
                    position.position_id,
                    position.symbol,
                    AlertLevel.INFO,
                    f"📈 Position at {position.profit_pct_of_max:.1f}% of max profit",
                    action_recommended="Consider taking profits early",
                    data={"pnl_pct": position.profit_pct_of_max, "type": "profit_reminder"}
                )
        
        return None
    
    # ══════════════════════════════════════════════════════════════════════════
    # NEWS MONITORING
    # ══════════════════════════════════════════════════════════════════════════
    
    async def _check_news_for_positions(self):
        """Check for breaking news affecting open positions"""
        
        for position_id, position in list(self.positions.items()):
            if position.status != "open":
                continue
            
            try:
                news = await self.financial.check_news(position.symbol)
                
                # Analyze news for potential impact
                if news and news.get("news_summary"):
                    impact = self._assess_news_impact(news.get("news_summary", ""))
                    
                    if impact == "high":
                        self._generate_alert(
                            position.position_id,
                            position.symbol,
                            AlertLevel.CRITICAL,
                            f"📰 HIGH IMPACT NEWS DETECTED for {position.symbol}",
                            action_recommended="Review news and consider closing position",
                            data={"news": news.get("news_summary", "")[:500]}
                        )
                    elif impact == "medium":
                        self._generate_alert(
                            position.position_id,
                            position.symbol,
                            AlertLevel.WARNING,
                            f"📰 News update for {position.symbol}",
                            data={"news": news.get("news_summary", "")[:500]}
                        )
            
            except Exception as e:
                logger.error(f"Error checking news for {position.symbol}: {e}")
    
    def _assess_news_impact(self, news_text: str) -> str:
        """Assess the potential impact of news on a position"""
        
        news_lower = news_text.lower()
        
        # High impact keywords
        high_impact = [
            "fda", "approval", "rejection", "recall",
            "lawsuit", "investigation", "fraud",
            "acquisition", "merger", "takeover",
            "bankruptcy", "default",
            "guidance cut", "warning", "downgrade",
            "ceo resign", "cfo resign", "executive departure",
            "data breach", "hack", "security incident"
        ]
        
        # Medium impact keywords
        medium_impact = [
            "upgrade", "downgrade", "analyst",
            "earnings", "revenue", "guidance",
            "partnership", "contract", "deal",
            "expansion", "restructuring",
            "dividend", "buyback"
        ]
        
        for keyword in high_impact:
            if keyword in news_lower:
                return "high"
        
        for keyword in medium_impact:
            if keyword in news_lower:
                return "medium"
        
        return "low"
    
    # ══════════════════════════════════════════════════════════════════════════
    # EXIT HANDLING
    # ══════════════════════════════════════════════════════════════════════════
    
    async def _trigger_exit(self, position: MonitoredPosition, reason: ExitReason):
        """Trigger an exit for a position"""
        
        logger.info(f"EXIT TRIGGERED: {position.symbol} - Reason: {reason.value}")
        
        position.exit_reason = reason
        
        # Call the exit callback if set
        if self.on_exit_signal:
            try:
                self.on_exit_signal(position, reason)
            except Exception as e:
                logger.error(f"Exit callback failed: {e}")
        
        # Attempt to close the position via Alpaca
        await self._execute_exit(position)
    
    async def _execute_exit(self, position: MonitoredPosition):
        """Execute the exit order"""
        
        try:
            # Build the Iron Condor order for closing
            ic_order = IronCondorOrder(
                underlying=position.symbol,
                expiration=position.expiration,
                put_long_strike=position.put_long_strike,
                put_short_strike=position.put_short_strike,
                call_short_strike=position.call_short_strike,
                call_long_strike=position.call_long_strike,
                contracts=position.contracts,
                limit_price=position.current_value * 1.02  # Pay slightly more to ensure fill
            )
            
            # Submit close order
            order_id = await self.alpaca.close_iron_condor(ic_order, limit_price=position.current_value * 1.02)
            
            if order_id:
                logger.info(f"Exit order submitted: {order_id}")
                position.status = "closing"
                
                self._generate_alert(
                    position.position_id,
                    position.symbol,
                    AlertLevel.INFO,
                    f"Exit order submitted (Order ID: {order_id})",
                    data={"order_id": order_id, "exit_reason": position.exit_reason.value}
                )
            else:
                logger.error(f"Failed to submit exit order for {position.symbol}")
                self._generate_alert(
                    position.position_id,
                    position.symbol,
                    AlertLevel.CRITICAL,
                    "⚠️ FAILED TO SUBMIT EXIT ORDER - Manual intervention required",
                    action_recommended="Close position manually"
                )
        
        except Exception as e:
            logger.error(f"Exit execution failed: {e}")
            self._generate_alert(
                position.position_id,
                position.symbol,
                AlertLevel.CRITICAL,
                f"⚠️ EXIT EXECUTION ERROR: {str(e)}",
                action_recommended="Close position manually"
            )
    
    # ══════════════════════════════════════════════════════════════════════════
    # ALERTING
    # ══════════════════════════════════════════════════════════════════════════
    
    def _generate_alert(
        self,
        position_id: str,
        symbol: str,
        level: AlertLevel,
        message: str,
        action_recommended: Optional[str] = None,
        data: Optional[Dict] = None
    ):
        """Generate an alert"""
        
        alert = Alert(
            timestamp=datetime.now(),
            position_id=position_id,
            symbol=symbol,
            level=level,
            message=message,
            action_recommended=action_recommended,
            data=data or {}
        )
        
        self.alerts.append(alert)
        self.alerts_generated += 1
        
        # Add to position alerts
        if position_id in self.positions:
            self.positions[position_id].alerts.append({
                "timestamp": alert.timestamp.isoformat(),
                "level": alert.level.value,
                "message": alert.message,
                **alert.data
            })
        
        # Log the alert
        log_msg = f"[{level.value.upper()}] {symbol}: {message}"
        if level == AlertLevel.CRITICAL:
            logger.critical(log_msg)
        elif level == AlertLevel.WARNING:
            logger.warning(log_msg)
        elif level == AlertLevel.ACTION_REQUIRED:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)
        
        # Call alert callback if set
        if self.on_alert:
            try:
                self.on_alert(alert)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")
    
    def get_recent_alerts(self, count: int = 10) -> List[Alert]:
        """Get the most recent alerts"""
        return self.alerts[-count:]
    
    def get_alerts_for_position(self, position_id: str) -> List[Alert]:
        """Get all alerts for a specific position"""
        return [a for a in self.alerts if a.position_id == position_id]
    
    # ══════════════════════════════════════════════════════════════════════════
    # STATUS & REPORTING
    # ══════════════════════════════════════════════════════════════════════════
    
    def get_status(self) -> Dict:
        """Get current monitoring status"""
        
        open_positions = [p for p in self.positions.values() if p.status == "open"]
        total_pnl = sum(p.unrealized_pnl for p in open_positions)
        
        return {
            "is_running": self.is_running,
            "total_positions": len(self.positions),
            "open_positions": len(open_positions),
            "total_unrealized_pnl": total_pnl,
            "checks_performed": self.checks_performed,
            "alerts_generated": self.alerts_generated,
            "positions_closed": self.positions_closed,
            "last_check": max(
                (p.last_check_time for p in self.positions.values() if p.last_check_time),
                default=None
            )
        }
    
    def get_position_summary(self) -> List[Dict]:
        """Get summary of all positions"""
        
        summaries = []
        for position in self.positions.values():
            summaries.append({
                "id": position.position_id,
                "symbol": position.symbol,
                "status": position.status,
                "contracts": position.contracts,
                "entry_credit": position.entry_credit,
                "current_price": position.current_underlying_price,
                "unrealized_pnl": position.unrealized_pnl,
                "pnl_pct_of_max": position.profit_pct_of_max if position.unrealized_pnl >= 0 else -position.loss_pct_of_max,
                "days_to_expiration": position.days_to_expiration,
                "alerts_count": len(position.alerts)
            })
        
        return summaries
    
    def print_status(self):
        """Print current status to console"""
        
        status = self.get_status()
        
        print("\n" + "=" * 60)
        print("ATLAS MONITORING STATUS")
        print("=" * 60)
        print(f"Running: {'✓' if status['is_running'] else '✗'}")
        print(f"Positions: {status['open_positions']} open / {status['total_positions']} total")
        print(f"Total P/L: ${status['total_unrealized_pnl']:,.2f}")
        print(f"Checks: {status['checks_performed']}")
        print(f"Alerts: {status['alerts_generated']}")
        
        if self.positions:
            print("\n" + "-" * 60)
            print("OPEN POSITIONS:")
            print("-" * 60)
            
            for summary in self.get_position_summary():
                if summary['status'] == 'open':
                    pnl_str = f"${summary['unrealized_pnl']:+,.2f}"
                    pct_str = f"({summary['pnl_pct_of_max']:+.1f}% of max)"
                    print(f"  {summary['symbol']}: {summary['contracts']} contracts | {pnl_str} {pct_str} | {summary['days_to_expiration']}d to exp")
        
        print("=" * 60 + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# STANDALONE TEST
# ══════════════════════════════════════════════════════════════════════════════

async def test_monitoring_engine():
    """Test the monitoring engine"""
    
    api_key = os.getenv("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_API_SECRET")
    perplexity_key = os.getenv("PERPLEXITY_API_KEY")
    
    if not api_key or not api_secret:
        print("Set ALPACA_API_KEY and ALPACA_API_SECRET environment variables")
        return
    
    # Initialize components
    alpaca = AlpacaClient(api_key, api_secret, paper=True)
    financial = FinancialDataService(perplexity_api_key=perplexity_key)
    
    config = MonitoringConfig(
        check_interval_seconds=10,  # Fast for testing
        profit_target_pct=50,
        max_loss_pct=75
    )
    
    monitor = MonitoringEngine(alpaca, financial, config)
    
    # Add a test position
    test_position = MonitoredPosition(
        position_id="test-001",
        symbol="SPY",
        put_long_strike=580.0,
        put_short_strike=585.0,
        call_short_strike=610.0,
        call_long_strike=615.0,
        expiration=date.today() + timedelta(days=7),
        contracts=1,
        entry_credit=1.50,
        entry_time=datetime.now(),
        entry_underlying_price=595.0
    )
    
    monitor.add_position(test_position)
    
    # Set up callbacks
    def on_alert(alert: Alert):
        print(f"\n🔔 ALERT: [{alert.level.value}] {alert.symbol}: {alert.message}")
    
    def on_exit(position: MonitoredPosition, reason: ExitReason):
        print(f"\n🚪 EXIT SIGNAL: {position.symbol} - {reason.value}")
    
    monitor.on_alert = on_alert
    monitor.on_exit_signal = on_exit
    
    try:
        print("Starting monitoring engine test...")
        print("Will run for 30 seconds with 10-second intervals")
        
        await monitor.start()
        
        # Run for 30 seconds
        await asyncio.sleep(30)
        
        # Print status
        monitor.print_status()
        
    finally:
        await monitor.stop()
        await alpaca.close()
        await financial.close()
        
        print("\n✓ Test completed!")


if __name__ == "__main__":
    asyncio.run(test_monitoring_engine())
