from datetime import date, timedelta

from atlas_financial import FinancialDataService, UpcomingEarnings


def test_validate_upcoming_earnings_ok():
    svc = FinancialDataService(perplexity_api_key=None)
    item = UpcomingEarnings(
        symbol="TEST",
        company_name="Test Co",
        earnings_date=date.today() + timedelta(days=2),
        earnings_time="AMC",
        eps_estimate=1.25,
        revenue_estimate=1000000.0,
        beat_rate=0.5,
        source="local",
        confidence="high",
        last_verified=date.today()
    )
    ok, errors = svc._validate_upcoming_earnings(item, days_ahead=7)
    assert ok
    assert errors == []


def test_cross_validate_low_confidence_on_mismatch():
    svc = FinancialDataService(perplexity_api_key=None)
    item = UpcomingEarnings(
        symbol="TEST",
        company_name="Test Co",
        earnings_date=date.today() + timedelta(days=2),
        earnings_time="AMC",
        eps_estimate=1.0,
        revenue_estimate=1000.0,
        source="perplexity",
        confidence="medium",
        last_verified=date.today()
    )
    yahoo_item = {
        "type": "upcoming",
        "date": (date.today() + timedelta(days=5)).isoformat(),
        "eps_estimate": 2.0,
        "revenue_estimate": 2000.0
    }
    confidence, reasons = svc._cross_validate_earnings(item, yahoo_item)
    assert confidence == "low"
    assert "date_mismatch" in reasons
