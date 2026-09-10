import unittest
import math
from datetime import datetime, timedelta
from sports_core.predictive_engine import FullTenDimensionsAnalyzer

class TestSportsIntelligenceEngine(unittest.TestCase):

    def setUp(self):
        self.analyzer = FullTenDimensionsAnalyzer(decay_lambda=0.045, dixon_coles_rho=-0.035)

    def test_dimension_1_exponential_decay(self):
        now = datetime(2026, 9, 10, 12, 0, 0)
        matches = [{"date": now - timedelta(days=10), "points": 3.0, "opponent_tier_weight": 1.0}]
        score = self.analyzer.compute_dimension_1_form(matches, now)
        self.assertAlmostEqual(score, 3.0, places=4)

    def test_dimension_2_altitude_adaptation(self):
        idx = self.analyzer.compute_dimension_2_environmental(venue_alt=2800.0, base_alt=0.0, delta_temp=0.0, delta_rh=0.0)
        delta_vo2 = 0.01 * ((2800.0 - 1500.0) / 100.0)
        expected = math.exp(-1.65 * delta_vo2)
        self.assertAlmostEqual(idx, expected, places=5)
        self.assertTrue(idx < 1.0)

    def test_dixon_coles_tau_independence(self):
        tau = self.analyzer.tau_adjustment(0, 0, lam=1.5, mu=1.2)
        expected = 1.0 - (1.5 * 1.2 * (-0.035))
        self.assertAlmostEqual(tau, expected, places=5)

    def test_full_dimensions_matrix_probabilities(self):
        result = self.analyzer.execute_full_dimensions(
            home_data={"attack_strength": 1.2, "defense_weakness": 1.0, "base_altitude_m": 0.0},
            away_data={"attack_strength": 1.0, "defense_weakness": 1.0, "base_altitude_m": 0.0},
            context={"altitude_m": 0.0, "execution_time": datetime.utcnow()}
        )
        total_prob = sum(sum(row) for row in result.score_matrix)
        self.assertTrue(0.90 <= total_prob <= 1.01)

if __name__ == "__main__":
    unittest.main()
