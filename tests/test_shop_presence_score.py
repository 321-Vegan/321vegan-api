import unittest
from datetime import datetime, timedelta

from app.crud.shop import ShopCRUDRepository

NOW = datetime(2026, 11, 26, 12, 0)


def days_ago(days):
    return NOW - timedelta(days=days)


def score(last_scanned=None, scan_count=0, last_found=None, not_found=()):
    return round(ShopCRUDRepository._compute_presence_score(
        NOW,
        last_scanned_at=days_ago(last_scanned) if last_scanned is not None else None,
        scan_count=scan_count,
        last_found_at=days_ago(last_found) if last_found is not None else None,
        report_dates=[days_ago(d) for d in not_found],
    ), 2)


class PresenceScoreTests(unittest.TestCase):
    def test_fresh_scan_is_near_certain(self):
        self.assertEqual(score(last_scanned=0, scan_count=1), 0.99)

    def test_fresh_found_report_counts_less_than_a_scan(self):
        self.assertEqual(score(last_found=0), 0.70)

    def test_found_report_fades_faster_than_a_scan(self):
        self.assertEqual(score(last_scanned=10, scan_count=1), 0.92)
        self.assertEqual(score(last_found=10), 0.62)
        self.assertEqual(score(last_scanned=20, scan_count=1), 0.69)
        self.assertEqual(score(last_found=20), 0.39)

    def test_old_found_report_keeps_the_floor(self):
        self.assertEqual(score(last_found=45), 0.15)

    def test_found_report_does_not_lower_a_recent_scan(self):
        self.assertEqual(score(last_scanned=0, scan_count=1, last_found=0), 0.99)

    def test_found_report_lifts_an_old_scan_to_its_own_ceiling_only(self):
        self.assertEqual(score(last_scanned=60, scan_count=1, last_found=0), 0.70)

    def test_not_found_report_lowers_a_found_report(self):
        self.assertEqual(score(last_found=10, not_found=[0]), 0.37)

    def test_not_found_report_removes_the_floor(self):
        self.assertEqual(score(last_found=45, not_found=[1]), 0.0)


if __name__ == "__main__":
    unittest.main()
