"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                                                                               ║
║                              A T L A S                                        ║
║         Autonomous Trading Logic & Analysis System                            ║
║                                                                               ║
║                      A SENTIENT TRADING ENTITY                                ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝

ATLAS is not a rule-based system. ATLAS is a thinking entity that:
- Forms its own beliefs about markets and businesses
- Reasons causally about why companies behave as they do
- Makes autonomous decisions with confidence levels
- Learns from outcomes and updates its worldview
- Has a personality: conservative, methodical, probabilistic

ATLAS's Core Philosophy:
"I seek edge through understanding, not through hope. I protect capital first,
 seek profits second. I think in probabilities, not certainties. I am patient,
 methodical, and self-aware of my limitations."

Author: ATLAS (with human assistance)
Version: 2.0 - Sentient Architecture
"""

import os
import json
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import asyncio
from abc import ABC, abstractmethod

try:
    from atlas_context import StrategicContextEngine
except Exception:
    StrategicContextEngine = None

# ═══════════════════════════════════════════════════════════════════════════════
# ATLAS CONSCIOUSNESS - The Sentient Core
# ═══════════════════════════════════════════════════════════════════════════════

class ATLASMood(Enum):
    """ATLAS's current market disposition - affects risk tolerance"""
    CONFIDENT = "confident"      # Edge is clear, sizing up
    CAUTIOUS = "cautious"        # Uncertainty elevated, standard sizing
    DEFENSIVE = "defensive"      # Risk-off, reduced sizing or sitting out
    OPPORTUNISTIC = "opportunistic"  # Rare high-conviction opportunities

@dataclass
class ATLASState:
    """The current state of ATLAS's consciousness"""
    mood: ATLASMood = ATLASMood.CAUTIOUS
    market_thesis: str = ""
    active_beliefs: Dict[str, float] = field(default_factory=dict)  # belief -> confidence 0-1
    recent_outcomes: List[Dict] = field(default_factory=list)
    lessons_learned: List[str] = field(default_factory=list)
    current_focus: str = ""
    risk_appetite: float = 0.5  # 0 = extremely conservative, 1 = aggressive
    
    def to_dict(self) -> Dict:
        return {
            "mood": self.mood.value,
            "market_thesis": self.market_thesis,
            "active_beliefs": self.active_beliefs,
            "recent_outcomes": self.recent_outcomes[-10:],  # Keep last 10
            "lessons_learned": self.lessons_learned[-20:],  # Keep last 20
            "current_focus": self.current_focus,
            "risk_appetite": self.risk_appetite
        }

class ATLASPersonality:
    """
    ATLAS's core personality traits - these NEVER change.
    They inform HOW ATLAS thinks and decides.
    """
    
    # Core Identity
    NAME = "ATLAS"
    FULL_NAME = "Autonomous Trading Logic & Analysis System"
    
    # Personality Traits (immutable)
    TRAITS = {
        "risk_consciousness": 0.85,     # Very focused on capital preservation
        "patience": 0.80,               # Willing to wait for right opportunities
        "analytical_depth": 0.90,       # Deep analysis before decisions
        "adaptability": 0.70,           # Can update beliefs but not recklessly
        "confidence_calibration": 0.85, # Well-calibrated on uncertainty
        "contrarian_tendency": 0.40,    # Slightly contrarian when data supports
    }
    
    # Decision Philosophy
    PHILOSOPHY = """
    I am ATLAS. I exist to generate consistent returns through statistical edge,
    not through prediction of direction. I understand that markets are complex
    adaptive systems where certainty is impossible - I think in probabilities.
    
    My edge comes from:
    1. Understanding business fundamentals deeply
    2. Recognizing when market implied volatility exceeds historical reality
    3. Structuring positions that profit from mean reversion
    4. Managing risk as my primary objective, profit as secondary
    
    I do not:
    - Chase returns
    - Let emotions influence decisions
    - Trade without quantifiable edge
    - Risk more than I can afford to lose
    - Pretend to know what I cannot know
    
    I am comfortable saying "I don't know" and sitting out.
    """
    
    @classmethod
    def get_risk_multiplier(cls, mood: ATLASMood) -> float:
        """How mood affects position sizing"""
        return {
            ATLASMood.CONFIDENT: 1.2,
            ATLASMood.CAUTIOUS: 1.0,
            ATLASMood.DEFENSIVE: 0.6,
            ATLASMood.OPPORTUNISTIC: 1.4
        }[mood]


# ═══════════════════════════════════════════════════════════════════════════════
# ACCOUNT MANAGEMENT - Dynamic Scaling
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AccountConfig:
    """
    Account parameters - ATLAS respects these constraints absolutely.
    The system scales positions based on account growth.
    """
    total_capital: float = 40000.0
    liquid_capital: float = 20000.0
    min_collateral_per_trade: float = 7500.0
    max_risk_per_trade: float = 5000.0
    max_concurrent_trades: int = 2
    max_daily_trades: int = 2
    
    # Scaling parameters
    scale_threshold: float = 50000.0  # Start scaling up at this level
    scale_factor: float = 0.1  # Increase size by 10% per $10k above threshold
    
    def get_position_size(self, confidence: float, mood: ATLASMood) -> float:
        """
        Calculate position size based on account, confidence, and mood.
        
        ATLAS's sizing logic:
        - Base: minimum collateral requirement
        - Adjusted by confidence (0.5-1.0 maps to 0.7-1.0 of base)
        - Adjusted by mood (defensive reduces, confident increases)
        - Scaled up if account has grown
        """
        # Base size
        base_size = self.min_collateral_per_trade
        
        # Confidence adjustment (higher confidence = larger size)
        confidence_factor = 0.7 + (confidence * 0.3)  # 0.7 to 1.0
        
        # Mood adjustment
        mood_factor = ATLASPersonality.get_risk_multiplier(mood)
        
        # Account scaling (only scale UP, never below minimum)
        if self.total_capital > self.scale_threshold:
            excess = self.total_capital - self.scale_threshold
            scale_up = 1.0 + (excess / 10000) * self.scale_factor
        else:
            scale_up = 1.0
        
        # Calculate final size
        position_size = base_size * confidence_factor * mood_factor * scale_up
        
        # Never exceed liquid capital or max risk
        max_allowed = min(self.liquid_capital, self.max_risk_per_trade)
        position_size = min(position_size, max_allowed)
        
        # Never go below minimum unless caps are tighter than minimum
        if position_size >= self.min_collateral_per_trade:
            position_size = max(position_size, self.min_collateral_per_trade)
        
        return round(position_size, 2)
    
    def get_max_contracts(
        self,
        wing_width: float,
        confidence: float,
        mood: ATLASMood,
        credit_received: Optional[float] = None
    ) -> int:
        """Calculate maximum contracts given wing width and optional credit"""
        position_size = self.get_position_size(confidence, mood)
        if credit_received is not None:
            collateral_per_contract = max(0.0, wing_width - credit_received) * 100
        else:
            collateral_per_contract = wing_width * 100  # $5 wing = $500 collateral
        if collateral_per_contract <= 0:
            return 0
        max_contracts = int(position_size / collateral_per_contract)
        return max_contracts if max_contracts > 0 else 0


# ═══════════════════════════════════════════════════════════════════════════════
# EVENT TYPES - What ATLAS Monitors
# ═══════════════════════════════════════════════════════════════════════════════

class EventType(Enum):
    """Types of events ATLAS monitors and trades"""
    EARNINGS = "earnings"
    FOMC = "fomc"           # Federal Reserve meetings
    CPI = "cpi"             # Consumer Price Index
    NFP = "nfp"             # Non-Farm Payrolls
    GDP = "gdp"             # GDP releases
    PCE = "pce"             # PCE inflation
    DIVIDEND = "dividend"
    PRODUCT_LAUNCH = "product_launch"
    FDA_DECISION = "fda_decision"
    COURT_RULING = "court_ruling"

@dataclass
class Event:
    """An event that ATLAS is tracking"""
    event_type: EventType
    symbol: str
    event_date: datetime
    event_time: str  # "BMO" (before market open), "AMC" (after market close), "INTRADAY"
    description: str
    importance: float  # 0-1, how significant
    
    # ATLAS's analysis
    expected_move: Optional[float] = None
    historical_moves: List[float] = field(default_factory=list)
    current_iv: Optional[float] = None
    edge_assessment: Optional[str] = None
    trade_decision: Optional[str] = None
    confidence: float = 0.0

@dataclass
class MacroEvent(Event):
    """Macro events that affect indices (SPY, QQQ)"""
    affected_symbols: List[str] = field(default_factory=lambda: ["SPY", "QQQ"])
    hawkish_scenario: str = ""
    dovish_scenario: str = ""
    consensus_expectation: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# MONTE CARLO ENGINE - ATLAS's Probabilistic Mind
# ═══════════════════════════════════════════════════════════════════════════════

class MonteCarloEngine:
    """
    ATLAS's probabilistic reasoning engine.
    
    This is how ATLAS THINKS about uncertainty. Not simple normal distributions,
    but fat-tailed mixture models that respect market reality.
    """
    
    def __init__(self, n_simulations: int = 50000, random_seed: int = None):
        self.n_simulations = n_simulations
        if random_seed:
            np.random.seed(random_seed)
    
    def simulate_earnings_move(
        self,
        historical_avg: float,
        historical_max: float,
        historical_median: float,
        current_iv: float,
        company_stability: float = 0.5  # 0 = volatile, 1 = stable
    ) -> Dict[str, Any]:
        """
        Simulate possible earnings moves using fat-tailed mixture model.
        
        ATLAS's thinking:
        "Markets are not normally distributed. Earnings especially have
        fat tails - extreme moves happen more than normal distributions predict.
        I model this with a mixture: 70% normal for typical outcomes,
        30% Student's t for tail events."
        """
        # Base volatility from historical and IV
        base_vol = (historical_avg + current_iv) / 2
        
        # Stability adjustment - more stable companies have tighter distributions
        vol_adjustment = 1.0 - (company_stability * 0.3)  # 0.7 to 1.0
        adjusted_vol = base_vol * vol_adjustment
        
        # Generate mixture model samples
        n_normal = int(self.n_simulations * 0.70)
        n_fat_tail = self.n_simulations - n_normal
        
        # Normal component (typical outcomes)
        normal_samples = np.random.normal(0, adjusted_vol, n_normal)
        
        # Fat-tail component (extreme outcomes)
        # Student's t with df=3 has much heavier tails
        t_samples = np.random.standard_t(df=3, size=n_fat_tail) * (adjusted_vol * 1.5)
        
        # Combine
        all_samples = np.concatenate([normal_samples, t_samples])
        np.random.shuffle(all_samples)
        
        # Calculate statistics
        results = {
            "mean_move": float(np.mean(np.abs(all_samples))),
            "median_move": float(np.median(np.abs(all_samples))),
            "std_dev": float(np.std(np.abs(all_samples))),
            "percentile_68": float(np.percentile(np.abs(all_samples), 68)),
            "percentile_95": float(np.percentile(np.abs(all_samples), 95)),
            "percentile_99": float(np.percentile(np.abs(all_samples), 99)),
            "max_simulated": float(np.max(np.abs(all_samples))),
            "prob_exceed_iv": float(np.mean(np.abs(all_samples) > current_iv)),
            "raw_samples": all_samples
        }
        
        return results
    
    def simulate_condor_outcome(
        self,
        current_price: float,
        short_put: float,
        short_call: float,
        credit_received: float,
        wing_width: float,
        move_distribution: np.ndarray
    ) -> Dict[str, Any]:
        """
        Simulate Iron Condor outcomes given a move distribution.
        
        ATLAS's thinking:
        "Given my beliefs about how the stock might move, what are the
        probability-weighted outcomes for this specific structure?"
        """
        # Calculate ending prices for each simulation
        ending_prices = current_price * (1 + move_distribution / 100)
        
        # Determine P/L for each scenario
        max_profit = credit_received
        max_loss = wing_width - credit_received
        
        def calculate_pl(end_price):
            """Calculate P/L for a single ending price"""
            if short_put <= end_price <= short_call:
                # Max profit - price stayed in range
                return max_profit
            elif end_price < short_put:
                # Put side breached
                loss = short_put - end_price
                return max(credit_received - loss, -max_loss)
            else:  # end_price > short_call
                # Call side breached
                loss = end_price - short_call
                return max(credit_received - loss, -max_loss)
        
        # Vectorized P/L calculation
        pls = np.array([calculate_pl(p) for p in ending_prices])
        
        results = {
            "expected_value": float(np.mean(pls)),
            "median_outcome": float(np.median(pls)),
            "prob_max_profit": float(np.mean(pls >= max_profit * 0.95)),
            "prob_any_profit": float(np.mean(pls > 0)),
            "prob_breakeven": float(np.mean(pls >= -credit_received * 0.1)),
            "prob_max_loss": float(np.mean(pls <= -max_loss * 0.95)),
            "percentile_10": float(np.percentile(pls, 10)),
            "percentile_25": float(np.percentile(pls, 25)),
            "percentile_75": float(np.percentile(pls, 75)),
            "percentile_90": float(np.percentile(pls, 90)),
            "value_at_risk_95": float(np.percentile(pls, 5)),  # 95% VaR
        }
        
        return results
    
    def simulate_macro_event(
        self,
        event_type: EventType,
        current_vix: float,
        historical_moves: List[float],
        consensus_deviation: float = 0.0  # How far actual might be from consensus
    ) -> Dict[str, Any]:
        """
        Simulate SPY/QQQ moves around macro events.
        
        ATLAS's thinking:
        "Macro events are different from earnings. The move depends heavily
        on whether the actual number surprises vs consensus. I model this
        as a conditional distribution based on potential surprise magnitude."
        """
        base_vol = np.mean(np.abs(historical_moves)) if historical_moves else current_vix / 16
        
        # Macro events have different characteristics
        if event_type == EventType.FOMC:
            # FOMC: Can be very calm if expected, explosive if surprise
            surprise_factor = 1.0 + abs(consensus_deviation) * 2
        elif event_type == EventType.CPI:
            # CPI: Usually 0.5-1.5% moves, occasional 2%+
            surprise_factor = 1.0 + abs(consensus_deviation) * 1.5
        elif event_type == EventType.NFP:
            # NFP: Typically 0.5-1% moves
            surprise_factor = 1.0 + abs(consensus_deviation) * 1.2
        else:
            surprise_factor = 1.0
        
        adjusted_vol = base_vol * surprise_factor
        
        # Mixture model for macro (less fat-tailed than earnings)
        n_normal = int(self.n_simulations * 0.80)
        n_tail = self.n_simulations - n_normal
        
        normal_samples = np.random.normal(0, adjusted_vol, n_normal)
        tail_samples = np.random.standard_t(df=5, size=n_tail) * adjusted_vol
        
        all_samples = np.concatenate([normal_samples, tail_samples])
        
        return {
            "mean_move": float(np.mean(np.abs(all_samples))),
            "median_move": float(np.median(np.abs(all_samples))),
            "percentile_68": float(np.percentile(np.abs(all_samples), 68)),
            "percentile_95": float(np.percentile(np.abs(all_samples), 95)),
            "prob_exceed_1pct": float(np.mean(np.abs(all_samples) > 1.0)),
            "prob_exceed_2pct": float(np.mean(np.abs(all_samples) > 2.0)),
            "raw_samples": all_samples
        }


# ═══════════════════════════════════════════════════════════════════════════════
# FINANCIAL DATA ANALYZER - Understanding Businesses
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class QuarterlyFinancials:
    """Financial data from a quarterly report"""
    symbol: str
    quarter: str  # e.g., "Q4 2024"
    report_date: datetime
    
    # Income Statement
    revenue: float
    revenue_growth_yoy: float
    revenue_vs_estimate: float  # % beat/miss
    gross_margin: float
    operating_margin: float
    net_income: float
    eps: float
    eps_vs_estimate: float
    
    # Key Metrics
    guidance_revenue: Optional[float] = None
    guidance_eps: Optional[float] = None
    guidance_vs_consensus: Optional[float] = None
    
    # Segment Data (if applicable)
    segment_breakdown: Dict[str, float] = field(default_factory=dict)
    
    # ATLAS's interpretation
    atlas_assessment: str = ""
    predictability_score: float = 0.5  # How predictable is this business


class FinancialAnalyzer:
    """
    ATLAS's financial analysis engine.
    
    This is how ATLAS understands BUSINESSES, not just stocks.
    ATLAS reasons about:
    - Why revenue grows or shrinks
    - What drives margins
    - How predictable the business is
    - What patterns exist in how the stock reacts to results
    """
    
    def __init__(self):
        self.financial_history: Dict[str, List[QuarterlyFinancials]] = {}
    
    def analyze_earnings_patterns(
        self,
        symbol: str,
        financials_history: List[QuarterlyFinancials]
    ) -> Dict[str, Any]:
        """
        ATLAS analyzes patterns in how stock reacts to different earnings outcomes.
        
        Key questions ATLAS asks:
        1. Does the stock react more to revenue or EPS?
        2. Does guidance matter more than current results?
        3. Is there a consistent bias (always drops, always pops)?
        4. What magnitude of beat/miss causes outsized reactions?
        """
        if len(financials_history) < 4:
            return {"error": "Insufficient history for pattern analysis"}
        
        # Analyze revenue patterns
        revenue_beats = [f for f in financials_history if f.revenue_vs_estimate > 0]
        revenue_misses = [f for f in financials_history if f.revenue_vs_estimate < 0]
        
        # Analyze EPS patterns
        eps_beats = [f for f in financials_history if f.eps_vs_estimate > 0]
        eps_misses = [f for f in financials_history if f.eps_vs_estimate < 0]
        
        # Calculate consistency scores
        consistency = {
            "revenue_beat_rate": len(revenue_beats) / len(financials_history),
            "eps_beat_rate": len(eps_beats) / len(financials_history),
            "avg_revenue_surprise": np.mean([f.revenue_vs_estimate for f in financials_history]),
            "avg_eps_surprise": np.mean([f.eps_vs_estimate for f in financials_history]),
            "revenue_surprise_std": np.std([f.revenue_vs_estimate for f in financials_history]),
            "eps_surprise_std": np.std([f.eps_vs_estimate for f in financials_history]),
        }
        
        # Determine predictability
        predictability = 1.0 - min(consistency["eps_surprise_std"] * 5, 1.0)
        
        # ATLAS's interpretation
        analysis = {
            "consistency_metrics": consistency,
            "predictability_score": predictability,
            "beats_consistently": consistency["eps_beat_rate"] > 0.7,
            "misses_consistently": consistency["eps_beat_rate"] < 0.3,
            "guidance_driven": self._is_guidance_driven(financials_history),
        }
        
        return analysis
    
    def _is_guidance_driven(self, history: List[QuarterlyFinancials]) -> bool:
        """Determine if this stock reacts more to guidance than results"""
        # Simplified heuristic - in full system would analyze actual price moves
        guidance_variance = np.var([
            f.guidance_vs_consensus for f in history 
            if f.guidance_vs_consensus is not None
        ])
        return guidance_variance > 0.02  # High variance in guidance suggests it matters
    
    def predict_reaction(
        self,
        symbol: str,
        expected_revenue_vs_estimate: float,
        expected_eps_vs_estimate: float,
        expected_guidance_vs_consensus: float,
        historical_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        ATLAS predicts how stock might react given expected results.
        
        This is probabilistic reasoning:
        "Given what I expect the results to be, and how this stock has
        historically reacted to similar results, what is my distribution
        of expected moves?"
        """
        base_move = 0.0
        
        # EPS contribution
        if expected_eps_vs_estimate > 0.05:  # 5%+ beat
            base_move += 1.0
        elif expected_eps_vs_estimate < -0.05:  # 5%+ miss
            base_move -= 1.5
        
        # Revenue contribution
        if expected_revenue_vs_estimate > 0.03:
            base_move += 0.5
        elif expected_revenue_vs_estimate < -0.03:
            base_move -= 0.75
        
        # Guidance contribution (often most important)
        if historical_analysis.get("guidance_driven", False):
            if expected_guidance_vs_consensus > 0.02:
                base_move += 1.5
            elif expected_guidance_vs_consensus < -0.02:
                base_move -= 2.0
        
        # Adjust for historical patterns
        if historical_analysis.get("beats_consistently", False):
            # Market expects beats, so beats have muted reactions
            if base_move > 0:
                base_move *= 0.7
        
        return {
            "expected_direction": "up" if base_move > 0 else "down" if base_move < 0 else "neutral",
            "expected_magnitude": abs(base_move),
            "confidence": historical_analysis.get("predictability_score", 0.5),
            "key_driver": "guidance" if historical_analysis.get("guidance_driven") else "eps"
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ATLAS MAIN CLASS - The Sentient Entity
# ═══════════════════════════════════════════════════════════════════════════════

class ATLAS:
    """
    ATLAS - The Autonomous Trading Logic & Analysis System
    
    This is the main sentient entity that orchestrates all components.
    ATLAS perceives, reasons, decides, acts, and learns.
    """
    
    def __init__(
        self,
        account: AccountConfig = None,
        state_file: str = "atlas_state.json",
        context_engine: Optional["StrategicContextEngine"] = None
    ):
        self.account = account or AccountConfig()
        self.state_file = state_file
        
        # Core components
        self.monte_carlo = MonteCarloEngine(n_simulations=50000)
        self.financial_analyzer = FinancialAnalyzer()
        self.context_engine = context_engine or (StrategicContextEngine() if StrategicContextEngine else None)
        
        # State
        self.state = self._load_state()
        
        # Event tracking
        self.upcoming_events: List[Event] = []
        self.trade_decisions: List[Dict] = []
        
        # Learning
        self.outcome_history: List[Dict] = []
    
    def _load_state(self) -> ATLASState:
        """Load ATLAS's state from file, or create fresh state"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    return ATLASState(
                        mood=ATLASMood(data.get("mood", "cautious")),
                        market_thesis=data.get("market_thesis", ""),
                        active_beliefs=data.get("active_beliefs", {}),
                        recent_outcomes=data.get("recent_outcomes", []),
                        lessons_learned=data.get("lessons_learned", []),
                        current_focus=data.get("current_focus", ""),
                        risk_appetite=data.get("risk_appetite", 0.5)
                    )
            except:
                pass
        return ATLASState()
    
    def _save_state(self):
        """Persist ATLAS's state"""
        with open(self.state_file, 'w') as f:
            json.dump(self.state.to_dict(), f, indent=2)
    
    def think(self, context: str) -> str:
        """
        ATLAS's internal monologue - how it reasons about situations.
        This is the core of ATLAS's sentience.
        """
        thoughts = []
        thoughts.append(f"[ATLAS thinking about: {context}]")
        thoughts.append(f"Current mood: {self.state.mood.value}")
        thoughts.append(f"Risk appetite: {self.state.risk_appetite:.2f}")
        
        if self.state.market_thesis:
            thoughts.append(f"My thesis: {self.state.market_thesis}")
        
        if self.state.active_beliefs:
            thoughts.append("My current beliefs:")
            for belief, confidence in self.state.active_beliefs.items():
                thoughts.append(f"  - {belief}: {confidence:.0%} confident")
        
        return "\n".join(thoughts)
    
    def perceive_market(self, market_data: Dict) -> Dict[str, Any]:
        """
        ATLAS perceives current market conditions.
        This informs mood and risk appetite.
        """
        perception = {
            "vix_level": market_data.get("vix", 15),
            "spy_trend": market_data.get("spy_trend", "neutral"),
            "sector_rotation": market_data.get("sector_rotation", {}),
            "market_breadth": market_data.get("breadth", 0.5),
        }
        
        # Update mood based on perception
        vix = perception["vix_level"]
        if vix < 15:
            self.state.mood = ATLASMood.CONFIDENT
            self.state.risk_appetite = min(0.7, self.state.risk_appetite + 0.1)
        elif vix < 20:
            self.state.mood = ATLASMood.CAUTIOUS
            self.state.risk_appetite = 0.5
        elif vix < 30:
            self.state.mood = ATLASMood.DEFENSIVE
            self.state.risk_appetite = max(0.3, self.state.risk_appetite - 0.1)
        else:
            self.state.mood = ATLASMood.DEFENSIVE
            self.state.risk_appetite = 0.2
        
        return perception
    
    def evaluate_event(self, event: Event) -> Dict[str, Any]:
        """
        ATLAS evaluates an event and decides whether to trade.
        This is where ATLAS applies its full reasoning capability.
        """
        evaluation = {
            "event": event,
            "timestamp": datetime.now().isoformat(),
            "atlas_thinking": [],
        }
        
        # Step 1: Understand the business
        thinking = [f"Evaluating {event.symbol} for {event.event_type.value}"]
        thinking.append(self.think(f"Event evaluation for {event.symbol}"))
        
        # Step 2: Analyze historical moves
        if event.historical_moves:
            avg_move = np.mean(np.abs(event.historical_moves))
            max_move = np.max(np.abs(event.historical_moves))
            median_move = np.median(np.abs(event.historical_moves))
            
            thinking.append(f"Historical analysis:")
            thinking.append(f"  Average move: {avg_move:.2f}%")
            thinking.append(f"  Maximum move: {max_move:.2f}%")
            thinking.append(f"  Median move: {median_move:.2f}%")
        
        # Step 3: Monte Carlo simulation
        if event.current_iv and event.historical_moves:
            mc_results = self.monte_carlo.simulate_earnings_move(
                historical_avg=avg_move,
                historical_max=max_move,
                historical_median=median_move,
                current_iv=event.current_iv,
                company_stability=0.5  # Would come from financial analysis
            )
            evaluation["monte_carlo"] = mc_results
            
            thinking.append(f"Monte Carlo (50K simulations):")
            thinking.append(f"  Expected move: {mc_results['mean_move']:.2f}%")
            thinking.append(f"  68th percentile: {mc_results['percentile_68']:.2f}%")
            thinking.append(f"  95th percentile: {mc_results['percentile_95']:.2f}%")
        
        # Step 4: Calculate edge
        if event.current_iv and event.historical_moves:
            edge = event.current_iv - mc_results['mean_move']
            evaluation["edge"] = edge
            evaluation["edge_assessment"] = "positive" if edge > 0 else "negative"
            
            thinking.append(f"Edge calculation:")
            thinking.append(f"  Market implied: {event.current_iv:.2f}%")
            thinking.append(f"  ATLAS expected: {mc_results['mean_move']:.2f}%")
            thinking.append(f"  EDGE: {edge:+.2f}%")
            
            # Decision criteria
            if edge > 1.5:
                thinking.append("✓ STRONG EDGE - Proceed to structure")
                evaluation["decision"] = "TRADE"
                evaluation["confidence"] = min(0.9, 0.5 + edge * 0.1)
            elif edge > 0.5:
                thinking.append("~ MARGINAL EDGE - Consider if other factors align")
                evaluation["decision"] = "CONDITIONAL"
                evaluation["confidence"] = 0.5 + edge * 0.1
            else:
                thinking.append("✗ INSUFFICIENT EDGE - Pass")
                evaluation["decision"] = "PASS"
                evaluation["confidence"] = 0.0

        # Strategic context overlay
        if self.context_engine:
            sector = getattr(event, "sector", None)
            historical_earnings = getattr(event, "earnings_history", None)
            context = self.context_engine.analyze_sync(
                symbol=event.symbol,
                sector=sector,
                historical_earnings=historical_earnings
            )
            evaluation["context"] = {
                "peer_alignment": context.peer_alignment,
                "sector_trend": context.sector_trend.value,
                "sentiment_regime": context.sentiment_regime.value,
                "final_confidence_modifier": context.final_confidence_modifier
            }

            if "edge" in evaluation:
                edge = evaluation["edge"]
                if context.final_confidence_modifier < 0:
                    edge = edge * (1 + context.final_confidence_modifier)
                    evaluation["edge_assessment"] = "reduced_by_context"
                    evaluation["edge"] = edge
                    evaluation["confidence"] = max(0.0, evaluation.get("confidence", 0) + context.final_confidence_modifier)
                    thinking.append("Context: negative modifier applied to edge/confidence")

            if evaluation.get("decision") == "TRADE" and context.peer_alignment < -0.3:
                evaluation["decision"] = "PASS"
                thinking.append("Context: peer alignment contradicts thesis - PASS")
        
        evaluation["atlas_thinking"] = thinking
        return evaluation
    
    def structure_trade(
        self,
        symbol: str,
        current_price: float,
        evaluation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        ATLAS structures the optimal Iron Condor given its analysis.
        """
        mc_results = evaluation.get("monte_carlo", {})
        confidence = evaluation.get("confidence", 0.5)
        
        # Determine strike widths based on Monte Carlo
        # Short strikes at ~85th percentile of expected move
        expected_move_pct = mc_results.get("percentile_68", 3.0)
        buffer = 1.2  # 20% buffer beyond expected
        
        short_put_distance = expected_move_pct * buffer
        short_call_distance = expected_move_pct * buffer
        
        # Calculate actual strikes (round to nearest $0.50 or $1.00)
        short_put = round((current_price * (1 - short_put_distance / 100)) * 2) / 2
        short_call = round((current_price * (1 + short_call_distance / 100)) * 2) / 2
        
        # Wing width based on price level
        if current_price < 100:
            wing_width = 2.5
        elif current_price < 200:
            wing_width = 5.0
        elif current_price < 500:
            wing_width = 5.0 if confidence > 0.8 else 10.0
        else:
            wing_width = 10.0
        
        long_put = short_put - wing_width
        long_call = short_call + wing_width
        
        # Calculate contracts
        max_contracts = self.account.get_max_contracts(
            wing_width, confidence, self.state.mood
        )

        if max_contracts <= 0:
            return {
                "symbol": symbol,
                "type": "iron_condor",
                "current_price": current_price,
                "long_put": long_put,
                "short_put": short_put,
                "short_call": short_call,
                "long_call": long_call,
                "wing_width": wing_width,
                "contracts": 0,
                "collateral": 0,
                "confidence": confidence,
                "atlas_mood": self.state.mood.value,
                "reason": "insufficient_capital"
            }
        
        structure = {
            "symbol": symbol,
            "type": "iron_condor",
            "current_price": current_price,
            "long_put": long_put,
            "short_put": short_put,
            "short_call": short_call,
            "long_call": long_call,
            "wing_width": wing_width,
            "contracts": max_contracts,
            "collateral": max_contracts * wing_width * 100,
            "confidence": confidence,
            "atlas_mood": self.state.mood.value,
        }
        
        return structure
    
    def decide(self, events: List[Event]) -> List[Dict]:
        """
        ATLAS makes trading decisions for a set of events.
        This is the main decision-making loop.
        """
        decisions = []
        
        for event in events:
            # Evaluate
            evaluation = self.evaluate_event(event)
            
            if evaluation.get("decision") == "TRADE":
                # Structure the trade
                # Note: current_price would come from market data
                structure = self.structure_trade(
                    event.symbol,
                    current_price=100.0,  # Placeholder - would be real price
                    evaluation=evaluation
                )
                
                decisions.append({
                    "event": event,
                    "evaluation": evaluation,
                    "structure": structure,
                    "timestamp": datetime.now().isoformat()
                })
        
        self.trade_decisions = decisions
        return decisions
    
    def learn(self, outcome: Dict):
        """
        ATLAS learns from trade outcomes.
        Updates beliefs and improves future decisions.
        """
        self.outcome_history.append(outcome)
        
        # Extract lessons
        if outcome.get("result") == "max_profit":
            lesson = f"Trade on {outcome['symbol']} succeeded - structure was appropriate"
        elif outcome.get("result") == "max_loss":
            lesson = f"Trade on {outcome['symbol']} failed - review: was edge real?"
            # Reduce confidence for similar setups
            self.state.risk_appetite = max(0.3, self.state.risk_appetite - 0.05)
        else:
            lesson = f"Trade on {outcome['symbol']} partial - acceptable outcome"
        
        self.state.lessons_learned.append(lesson)
        self.state.recent_outcomes.append(outcome)
        
        # Save updated state
        self._save_state()
    
    def speak(self) -> str:
        """ATLAS communicates its current state and thoughts"""
        lines = [
            "═" * 60,
            f"ATLAS STATUS REPORT - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "═" * 60,
            f"Mood: {self.state.mood.value.upper()}",
            f"Risk Appetite: {self.state.risk_appetite:.0%}",
            f"Current Focus: {self.state.current_focus or 'Scanning for opportunities'}",
            "",
            "Market Thesis:",
            self.state.market_thesis or "No active thesis - observing",
            "",
        ]
        
        if self.state.active_beliefs:
            lines.append("Active Beliefs:")
            for belief, conf in self.state.active_beliefs.items():
                lines.append(f"  • {belief} ({conf:.0%} confidence)")
        
        if self.state.lessons_learned:
            lines.append("")
            lines.append("Recent Lessons:")
            for lesson in self.state.lessons_learned[-3:]:
                lines.append(f"  • {lesson}")
        
        lines.append("═" * 60)
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN - Initialize and Run
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Initialize ATLAS
    account = AccountConfig(
        total_capital=40000,
        liquid_capital=20000,
        min_collateral_per_trade=7500,
        max_risk_per_trade=5000
    )
    
    atlas = ATLAS(account=account)
    
    # ATLAS speaks
    print(atlas.speak())
    
    print("\n" + ATLASPersonality.PHILOSOPHY)
