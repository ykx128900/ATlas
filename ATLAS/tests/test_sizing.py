from atlas_core import AccountConfig, ATLASMood


def test_sizing_respects_max_risk():
    account = AccountConfig(
        total_capital=40000,
        liquid_capital=10000,
        min_collateral_per_trade=1000,
        max_risk_per_trade=2000
    )
    contracts = account.get_max_contracts(
        wing_width=5.0,
        confidence=0.9,
        mood=ATLASMood.CAUTIOUS,
        credit_received=1.0
    )
    # collateral per contract = (5-1)*100 = 400
    assert contracts * 400 <= account.max_risk_per_trade


def test_sizing_returns_zero_if_insufficient_capital():
    account = AccountConfig(
        total_capital=10000,
        liquid_capital=500,
        min_collateral_per_trade=500,
        max_risk_per_trade=300
    )
    contracts = account.get_max_contracts(
        wing_width=5.0,
        confidence=0.5,
        mood=ATLASMood.CAUTIOUS,
        credit_received=1.0
    )
    # collateral per contract = 400, position size capped at 300 => 0 contracts
    assert contracts == 0
