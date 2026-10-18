from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from scraper import parse_dws_station_table


class ScraperAndApiTests(unittest.TestCase):
    def test_dws_table_parser_preserves_source_and_timestamp(self) -> None:
        html = """
        <table><tr><th>Station</th></tr>
        <tr><td>C1H019</td><td>Grootdraai</td><td>2026-10-09 12:00</td><td>0.843</td><td>10.52</td></tr>
        </table>
        """
        rows = parse_dws_station_table(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["station_id"], "C1H019")
        self.assertEqual(rows[0]["source"], "dws_unverified_near_real_time")
        self.assertTrue(rows[0]["timestamp"].endswith("+00:00"))

    def test_fastapi_model_info_and_dashboard_contract(self) -> None:
        raw = [
            {
                "station_id": "C1H019",
                "name": "Test station",
                "timestamp": "2026-10-09T12:00:00+00:00",
                "current_value": 0.9,
                "source": "dws_unverified_near_real_time",
            }
        ]
        with patch("main._raw_stations", return_value=raw):
            client = TestClient(main.app)
            info = client.get("/api/model-info")
            dashboard = client.get("/api/dashboard")
        self.assertEqual(info.status_code, 200)
        self.assertEqual(dashboard.status_code, 200)
        body = dashboard.json()[0]
        self.assertIn("trust_components", body)
        self.assertIn("anomaly_reasons", body)
        self.assertIn("model_available", body["forecast"])
        self.assertIn("requires_human_review", body["alert"])

    def test_feedback_does_not_claim_model_merge(self) -> None:
        client = TestClient(main.app)
        response = client.post(
            "/api/feedback",
            json={"station_id": "C1H019", "report": "River appears stable", "lang": "Sepedi"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("no Trust Score change", response.json()["impact"])


if __name__ == "__main__":
    unittest.main()

