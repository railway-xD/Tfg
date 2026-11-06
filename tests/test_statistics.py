import unittest
from bot.services.statistics import overs_text, strike_rate, economy, run_rate, extras_total

class CricketStatisticsTests(unittest.TestCase):
    def test_overs(self):
        self.assertEqual(overs_text(17), "2.5")
        self.assertEqual(overs_text(6), "1.0")

    def test_rates(self):
        self.assertEqual(strike_rate(18, 8), 225.0)
        self.assertEqual(economy(12, 12), 6.0)
        self.assertEqual(run_rate(24, 12), 12.0)
        self.assertEqual(strike_rate(0, 0), 0.0)

    def test_extras(self):
        self.assertEqual(extras_total({"wides": 1, "no_balls": 2, "byes": 0}), 3)

if __name__ == "__main__":
    unittest.main()
