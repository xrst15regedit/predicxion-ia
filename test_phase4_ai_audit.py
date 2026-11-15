import os
import sys
import types
import unittest
from unittest.mock import MagicMock

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


class TestPhase4AIAuditAndUI(unittest.TestCase):
    def setUp(self):
        pred_app._VERIFIED_RESULTS_CACHE.clear()
        pred_app.VERIFIED_TEAM_HISTORY.clear()
        pred_app.RATINGS_REALES.clear()
        pred_app.MatchEnrichmentCache._STORE.clear()
        pred_app.db = None

    def _add_verified_team(self, team, code="PL", liga="Premier League", gf=2, ga=1):
        for i in range(1, 6):
            pred_app._VERIFIED_RESULTS_CACHE[(f"2026-10-1{i}", team, f"Rival_{team}_{i}")] = {
                "finished": True,
                "simulado": False,
                "competicion": liga,
                "codigo_liga": code,
                "score_home": gf,
                "score_away": ga,
                "source": "football-data.org",
                "tipo_entidad": "club",
            }

    def test_01_ai_returns_datos_insuficientes_when_match_lacks_verified_sample(self):
        an = pred_app.SportsAnalyticsEngine.generate_institutional_analysis({
            "local": "SinDatosLoc",
            "visitante": "SinDatosVis",
            "codigo_liga": "PL",
            "liga": "Premier League",
            "fecha": "2026-11-15",
        })
        ai = an["consenso_dual_ia"]
        self.assertEqual(ai["estado"], "DATOS_INSUFICIENTES")
        self.assertEqual(ai["seleccion_final_consenso"], "Datos insuficientes")
        self.assertEqual(ai["probabilidad_consenso"], "—")
        self.assertIn("Datos insuficientes", ai["gemini_tesis"])

    def test_02_ai_uses_verified_facts_and_never_invents_corners_or_cards(self):
        self._add_verified_team("Arsenal", gf=2, ga=0)
        self._add_verified_team("Chelsea", gf=1, ga=2)
        an = pred_app.SportsAnalyticsEngine.generate_institutional_analysis({
            "local": "Arsenal",
            "visitante": "Chelsea",
            "codigo_liga": "PL",
            "liga": "Premier League",
            "fecha": "2026-11-15",
        })
        ai = an["consenso_dual_ia"]
        self.assertEqual(ai["estado"], "ACTIVO")
        self.assertNotIn("9.8 córners", ai["gemini_tesis"])
        self.assertIn("Datos insuficientes", ai["gemini_tesis"])

    def test_03_audit_enrichment_never_invents_36_cards_or_94_corners(self):
        item = {
            "local": "Arsenal",
            "visitante": "Chelsea",
            "liga": "Premier League",
            "categoria": "CORNERS",
            "fecha_utc": "2026-11-15T15:00:00Z",
            "an_data": {"key_probabilities": {"avg_corners": {"value": None}}, "parametros_xg": {}},
        }
        res = pred_app._enriquecer_pick_con_estado_auditoria(item, "2026-11-15")
        self.assertEqual(res["promedio_mercado_valor"], "Datos insuficientes")
        self.assertEqual(res["estado_partido"], "ACTIVO")
        self.assertIsNone(res["marcador_final"])

    def test_04_frontend_html_uses_top3_labels(self):
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("Top 3 del Día", html)
        self.assertIn("Desbloquear Top 3 VIP", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)