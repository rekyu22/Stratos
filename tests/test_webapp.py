import os
import unittest

from fastapi.testclient import TestClient

os.environ["STRATOS_SOURCE"] = "sim"
os.environ["STRATOS_SIM_HZ"] = "20"
os.environ["STRATOS_LOG"] = "0"

import webapp


class TestWebApp(unittest.TestCase):
    def test_rest_endpoints(self):
        with TestClient(webapp.app) as client:
            status = client.get("/api/status")
            self.assertEqual(status.status_code, 200)
            payload = status.json()
            self.assertIn("frames_received", payload)
            self.assertIn("rx_fps", payload)

            latest = client.get("/api/latest")
            self.assertEqual(latest.status_code, 200)
            self.assertIn("sample", latest.json())

            history = client.get("/api/history?points=10")
            self.assertEqual(history.status_code, 200)
            self.assertIn("samples", history.json())

    def test_history_csv_endpoint(self):
        with TestClient(webapp.app) as client:
            response = client.get("/api/history.csv?points=20")
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/csv", response.headers.get("content-type", ""))
            content_disposition = response.headers.get("content-disposition", "")
            self.assertIn("stratos_history.csv", content_disposition)
            self.assertIn("timestamp,frame_id", response.text)

    def test_switch_source_endpoint(self):
        with TestClient(webapp.app) as client:
            response = client.post("/api/source", json={"mode": "sim"})
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload.get("ok"))
            self.assertIn("status", payload)

    def test_websocket_live(self):
        with TestClient(webapp.app) as client:
            with client.websocket_connect("/ws/live?points=5&period_ms=120") as websocket:
                payload = websocket.receive_json()
                self.assertIn("status", payload)
                self.assertIn("latest", payload)
                self.assertIn("history", payload)


if __name__ == "__main__":
    unittest.main()
