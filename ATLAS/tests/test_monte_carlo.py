import numpy as np

from atlas_core import MonteCarloEngine


def test_simulate_earnings_move_output_shape():
    engine = MonteCarloEngine(n_simulations=10000, random_seed=42)
    result = engine.simulate_earnings_move(
        historical_avg=3.0,
        historical_max=7.0,
        historical_median=2.5,
        current_iv=4.0,
        company_stability=0.6
    )

    # Required keys
    required = {
        "mean_move",
        "median_move",
        "std_dev",
        "percentile_68",
        "percentile_95",
        "percentile_99",
        "prob_exceed_iv",
    }
    assert required.issubset(set(result.keys()))

    # Percentiles should be ordered
    assert result["percentile_68"] <= result["percentile_95"] <= result["percentile_99"]

    # Probabilities in [0,1]
    assert 0.0 <= result["prob_exceed_iv"] <= 1.0

    # Reasonable magnitude
    assert result["mean_move"] > 0
    assert result["median_move"] > 0
    assert result["std_dev"] > 0
