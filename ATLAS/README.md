# ATLAS Production System - Deployment Guide

## Overview
ATLAS (Autonomous Trading Logic & Analysis System) is a sentient trading entity for automated Iron Condor execution around earnings events.

**Account Configuration:** $40K total, $20K liquid, $7.5K min collateral/trade

## Files

| File | Size | Purpose |
|------|------|---------|
| `atlas_production.py` | Main | Orchestrates daily cycle: Perceive → Analyze → Reason → Decide → Plan |
| `atlas_alpaca.py` | 1200 lines | Real-time options data, paper trading execution via Alpaca |
| `atlas_financial.py` | 1100 lines | Perplexity Finance + Yahoo + Google Finance (cascading) |
| `atlas_monitor.py` | 900 lines | 5-minute position/news monitoring, automatic exits |
| `atlas_core.py` | 908 lines | Core ATLAS logic, Monte Carlo engine, personality |

## Quick Start (Monday Deployment)

### 1. Set Environment Variables
```bash
export ALPACA_API_KEY="your-paper-trading-key"
export ALPACA_API_SECRET="your-paper-trading-secret"
export PERPLEXITY_API_KEY="your-perplexity-key"
```

### 2. Install Dependencies
```bash
pip install aiohttp numpy
```

### 3. Run Production
```bash
cd ATLAS_Production

# Check status
python atlas_production.py --status

# Run daily scan only
python atlas_production.py --scan

# Full production mode (recommended)
python atlas_production.py --run
```

## Daily Cycle

| Time (ET) | Action |
|-----------|--------|
| 9:00 AM | Daily scan: Identify earnings candidates from 60+ symbol watchlist |
| 3:00-3:45 PM | Entry window: Execute selected trades |
| Every 5 min | Monitor positions: P/L, strike threats, news |
| Auto | Exit when: 50% profit, 75% loss, strike breach, news impact |

## Key Features

### Real-Time Data (Alpaca)
- Live options chains with Greeks (delta, gamma, theta, vega)
- 2-year historical options data for learning
- Paper trading execution via multi-leg orders
- Rate limit: 200 requests/minute

### Financial Intelligence (Perplexity → Yahoo → Google)
- Upcoming earnings (7 days ahead)
- 8 quarters earnings history
- Tradability assessment (0-100 score)
- Macro events (FOMC, CPI, NFP)
- Breaking news monitoring

### Autonomous Decision Making
- 50,000 Monte Carlo simulations per candidate
- Fat-tailed distributions (70% Normal + 30% Student's t)
- Edge = Current IV - Expected Move
- Selection criteria: Edge ≥ 1.0%, Confidence ≥ 60%

### Exit Management
- **Profit Target:** 50% of max profit → Close
- **Stop Loss:** 75% of max loss → Close
- **Strike Breach:** Price touches short strike → Close
- **Expiration Near:** 3 hours before → Close
- **News Event:** High-impact breaking news → Alert

### Learning System
- Records every trade outcome
- Updates beliefs about symbols (0.1-1.0 confidence)
- Adjusts mood: Confident (1.2×), Cautious (1.0×), Defensive (0.6×)
- Extracts lessons from each trade

## Watchlist (60+ Symbols)

- **Consumer Staples:** PEP, KO, PG, CL
- **Pharma:** MRK, PFE, BMY, ABBV
- **Healthcare:** UNH, CI, CVS, HUM
- **Financial Infrastructure:** CME, ICE, CBOE
- **Industrial Gases:** LIN, APD
- **Utilities:** NEE, DUK, SO
- **Defense:** RTX, LMT, NOC
- **Index ETFs:** SPY, QQQ, IWM

## State Files (Auto-Created)

- `atlas_config.json` - Account configuration
- `atlas_state.json` - ATLAS mood, beliefs, lessons
- `atlas_positions.json` - Open positions
- `atlas_history.json` - Complete trade history
- `logs/atlas_YYYYMMDD.log` - Daily logs

## Getting Alpaca Paper Trading Keys

1. Go to https://alpaca.markets
2. Create free account
3. In dashboard, select "Paper Trading"
4. Generate API keys (Key ID + Secret)

## Graceful Shutdown

Press `Ctrl+C` to stop. System will:
1. Cancel pending orders
2. Save current state
3. Log shutdown
