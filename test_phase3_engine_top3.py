import inspect
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


class TestPhase3Strict(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flask_app = pred_app.create_app()

    def setUp(self):
        pred_app._VERIFIED_RESULTS_CACHE.clear()
        pred_app.VERIFIED_TEAM_HISTORY.clear()
        pred_app.RATINGS_REALES.clear()
        pred_app.MatchEnrichmentCache._STORE.clear()
        pred_app.db = None
        flask_stub.request.args = {}

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

    def test_01_full_app_no_vedve_no_historical_top5_and_no_engine_boosts(self):
        app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            full_src = f.read()

        # Ningún uso de "V-E-D-V-E" en todo app.py
        self.assertNotIn("V-E-D-V-E", full_src, "Aún existe 'V-E-D-V-E' en app.py")
        # _HISTORICAL_ISSUED_TOP5 completamente vacío y aislado
        self.assertEqual(getattr(pred_app, "_HISTORICAL_ISSUED_TOP5", {}), {})
        self.assertNotIn("_HISTORICAL_ISSUED_TOP5[", full_src)
        self.assertNotIn("_HISTORICAL_ISSUED_TOP5.keys()", full_src)

        # Sin incrementos ni pisos artificiales en el motor
        eng_src = inspect.getsource(pred_app.SportsAnalyticsEngine.generate_institutional_analysis)
        for inc in ("+ 10.0", "+ 12.0", "+ 18.0", "+ 8.0", "+ 7.0", "+ 6.0", "+ 4.0", "+ 3.0", "+ 14.0"):
            self.assertNotIn(inc, eng_src, f"Incremento artificial encontrado en motor: {inc}")
        for floor in ("max(75", "max(76", "max(77", "max(78", "max(79", "max(80"):
            self.assertNotIn(floor, eng_src, f"Piso artificial encontrado en motor: {floor}")

    def test_02_unverified_streak_never_produces_five_results_or_vedve(self):
        pts, w, d, l = pred_app.SportsAnalyticsEngine._calcular_puntos_racha5("")
        self.assertEqual((pts, w, d, l), (0, 0, 0, 0))

        stats = pred_app.SportsAnalyticsEngine.get_team_stats("EquipoInexistenteXYZ", "PL", before_date="2026-11-15")
        self.assertEqual(stats["streak"], "")
        self.assertEqual(stats["muestra_n"], 0)
        self.assertEqual(stats["nivel_verificacion"], "DATOS_INSUFICIENTES")

        an = pred_app.SportsAnalyticsEngine.generate_institutional_analysis({
            "local": "SinDatosLoc",
            "visitante": "SinDatosVis",
            "codigo_liga": "PL",
            "liga": "Premier League",
            "fecha": "2026-11-15",
        })
        dinamica = an["pilares_cuantitativos"]["pilar_3_forma_momentum"]["dinamica"]
        self.assertNotIn("V-E-D-V-E", dinamica)
        self.assertIn("Sin partidos verificados", dinamica)
        self.assertIn("0/0 pts", dinamica)

    def test_03_1x2_sums_to_100_and_fair_odds_separated_from_real_odds(self):
        self._add_verified_team("Arsenal", gf=2, ga=0)
        self._add_verified_team("Chelsea", gf=1, ga=2)
        an = pred_app.SportsAnalyticsEngine.generate_institutional_analysis({
            "local": "Arsenal",
            "visitante": "Chelsea",
            "codigo_liga": "PL",
            "liga": "Premier League",
            "fecha": "2026-11-15",
        })
        p1x2 = an["probabilidades"]["1X2"]
        self.assertAlmostEqual(p1x2["1"] + p1x2["X"] + p1x2["2"], 100.0, delta=0.15)

        p_princ = an["pronostico_principal"]
        self.assertFalse(p_princ["es_cuota_real"])
        self.assertIsNone(p_princ["cuota_real"])
        self.assertEqual(
            p_princ["cuota_justa_modelo"],
            round(100.0 / max(5.0, min(95.0, float(p_princ["confidence_pct"]))), 2),
        )
        ev_card = next(c for c in an["consenso_5_modelos"] if c["id"] == "valor_cuota")
        self.assertIn("sin cuota real de mercado", ev_card["metrica"])
        self.assertNotIn("Supera en +", ev_card["metrica"])

    def test_04_historical_date_returns_no_hardcoded_picks_and_top3_max_3(self):
        # Consultar fechas que antes estaban en _HISTORICAL_ISSUED_TOP5 ("2026-10-18", "2026-10-19")
        handler_top3 = self.flask_app.routes["/api/v1/top3/daily"]
        for hist_date in ("2026-10-18", "2026-10-19"):
            flask_stub.request.args = {"fecha": hist_date}
            resp = handler_top3()
            self.assertEqual(resp["top3"], [])
            self.assertEqual(resp["top5"], [])

        # Con 4 partidos verificados -> máximo 3 selecciones, sin cuota real inventada
        for h, a in [("Arsenal", "Chelsea"), ("Liverpool", "Everton"), ("Manchester City", "Fulham"), ("Newcastle", "Brighton")]:
            self._add_verified_team(h, gf=2, ga=0)
            self._add_verified_team(a, gf=1, ga=1)

        matches_day = [
            {"id_partido": "p1", "local": "Arsenal", "visitante": "Chelsea", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-15T14:00:00Z"},
            {"id_partido": "p2", "local": "Liverpool", "visitante": "Everton", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-15T15:00:00Z"},
            {"id_partido": "p3", "local": "Manchester City", "visitante": "Fulham", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-15T16:00:00Z"},
            {"id_partido": "p4", "local": "Newcastle", "visitante": "Brighton", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-15T17:00:00Z"},
        ]
        top3 = pred_app._seleccionar_top3_verificado(matches_day, "2026-11-15", limit=5)
        self.assertLessEqual(len(top3), 3)
        self.assertEqual(len(top3), 3)
        for pick in top3:
            self.assertFalse(pick["es_cuota_real"])
            self.assertIsNone(pick["cuota_real"])


if __name__ == "__main__":
    unittest.main(verbosity=2)