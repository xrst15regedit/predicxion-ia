import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch
import requests

os.environ["DISABLE_BACKGROUND_WORKERS"] = "true"
os.environ["DISABLE_FIREBASE_INIT"] = "true"
os.environ["FOOTBALL_API_KEY"] = "test_secret_api_key_12345"
os.environ["ALLOW_SIMULATED_ACTA"] = "false"

flask_stub = types.ModuleType("flask")


class _FakeFlask:
    def __init__(self, *args, **kwargs):
        self.config = {}
        self.routes = {}

    def route(self, rule, *args, **kwargs):
        def decorator(fn):
            self.routes[rule] = fn
            return fn
        return decorator

    def before_request(self, fn):
        return fn

    def after_request(self, fn):
        return fn

    def errorhandler(self, *args, **kwargs):
        def decorator(fn):
            return fn
        return decorator


flask_stub.Flask = _FakeFlask
flask_stub.request = MagicMock()
flask_stub.request.args = {}
flask_stub.jsonify = lambda *a, **kw: (a[0] if a else kw)
flask_stub.g = MagicMock()
flask_stub.send_file = MagicMock()
flask_stub.render_template = MagicMock()
flask_stub.Response = MagicMock()
flask_stub.redirect = MagicMock()
sys.modules["flask"] = flask_stub

flask_cors_stub = types.ModuleType("flask_cors")
flask_cors_stub.CORS = lambda *a, **kw: None
sys.modules["flask_cors"] = flask_cors_stub

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as pred_app


class TestPhase2Calendar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flask_app = pred_app.create_app()

    def setUp(self):
        pred_app.CalendarSyncService._STATUS_OVERLAY.clear()
        pred_app.CalendarSyncService._LAST_AUDIT = None
        pred_app.db = None

    def test_01_canonical_key_prevents_false_collisions_and_catches_aliases(self):
        k1 = pred_app.CalendarSyncService.canonical_fixture_key("Manchester City", "Liverpool", "2026-11-15")
        k2 = pred_app.CalendarSyncService.canonical_fixture_key("Manchester United", "Liverpool", "2026-11-15")
        self.assertNotEqual(k1, k2)

        k_a = pred_app.CalendarSyncService.canonical_fixture_key("Atlético Madrid", "Real Madrid", "2026-11-15")
        k_b = pred_app.CalendarSyncService.canonical_fixture_key("Atletico Madrid", "Real Madrid", "2026-11-15")
        self.assertEqual(k_a, k_b)

    def test_02_audit_manual_calendar_detects_duplicates_and_mal_asignados(self):
        sample_pool = [
            {"id_partido": "f1", "local": "Arsenal", "visitante": "Chelsea", "fecha_utc": "2026-11-15T14:00:00Z", "codigo_liga": "PL"},
            {"id_partido": "f2", "local": "Arsenal", "visitante": "Chelsea", "fecha_utc": "2026-11-15T16:00:00Z", "codigo_liga": "PL"},
            {"id_partido": "f3", "local": "Equipo X", "visitante": "Equipo Y", "fecha_utc": "2026-11-15T18:00:00Z", "codigo_liga": "INVALIDA"},
        ]
        audit = pred_app.CalendarSyncService.audit_manual_calendar(sample_pool)
        self.assertEqual(audit["total_manual"], 3)
        self.assertEqual(audit["total_duplicados"], 1)
        self.assertEqual(audit["total_mal_asignados"], 1)

    def test_03_sync_verify_detects_missing_and_date_mismatch_without_overwriting_manual(self):
        manual_pool = [
            {"id_partido": "m1", "local": "Arsenal", "visitante": "Chelsea", "fecha_utc": "2026-11-15T15:00:00Z", "codigo_liga": "PL", "estado": "SCHEDULED"},
            {"id_partido": "m2", "local": "Liverpool", "visitante": "Everton", "fecha_utc": "2026-11-16T15:00:00Z", "codigo_liga": "PL", "estado": "SCHEDULED"},
        ]
        fd_payload = {
            "matches": [
                {"homeTeam": {"name": "Arsenal"}, "awayTeam": {"name": "Chelsea"}, "utcDate": "2026-11-15T15:00:00Z", "status": "SCHEDULED"},
                {"homeTeam": {"name": "Liverpool"}, "awayTeam": {"name": "Everton"}, "utcDate": "2026-11-18T20:00:00Z", "status": "POSTPONED"},
                {"homeTeam": {"name": "Tottenham"}, "awayTeam": {"name": "Fulham"}, "utcDate": "2026-11-17T19:00:00Z", "status": "SCHEDULED"},
            ]
        }
        with patch.object(pred_app.FootballDataOrgClient, "fetch_json", return_value={"ok": True, "data": fd_payload}):
            report = pred_app.CalendarSyncService.sync_verify_with_football_data(
                competition_codes=["PL"], fixtures=manual_pool
            )

        self.assertTrue(report["calendario_manual_intacto"])
        self.assertEqual(report["verificados_con_fd"], 1)
        self.assertEqual(len(report["fechas_discrepantes"]), 1)
        self.assertEqual(report["fechas_discrepantes"][0]["fecha_manual"], "2026-11-16")
        self.assertEqual(report["fechas_discrepantes"][0]["fecha_football_data"], "2026-11-18")
        self.assertEqual(len(report["faltantes_en_manual"]), 1)
        self.assertEqual(report["faltantes_en_manual"][0]["local"], "Tottenham")
        # Calendario manual no fue modificado ni eliminado
        self.assertEqual(manual_pool[1]["fecha_utc"], "2026-11-16T15:00:00Z")

        ov = pred_app.CalendarSyncService.get_fixture_overlay(manual_pool[1])
        self.assertTrue(ov["discrepancia_fecha"])
        self.assertEqual(ov["estado_verificado"], "POSTPONED")

    def test_04_admin_calendar_routes_registered_and_obtener_pronostico_zero_http(self):
        self.assertIn("/api/v1/admin/calendar/audit", self.flask_app.routes)
        self.assertIn("/api/v1/admin/calendar/sync-verify", self.flask_app.routes)

        handler = self.flask_app.routes["/obtener-pronostico"]
        with patch.object(requests, "get", side_effect=AssertionError("HTTP externo prohibido en /obtener-pronostico")):
            resp, status_code = handler()
            self.assertEqual(status_code, 200)
            self.assertTrue(resp["destacados"])
            self.assertIn("estado_calendario", resp["destacados"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)