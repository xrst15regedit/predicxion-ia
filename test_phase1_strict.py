import json
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch
import requests

# Aislamiento total para entorno limpio (sin hilos de arranque, sin Firebase real ni red)
os.environ["DISABLE_BACKGROUND_WORKERS"] = "true"
os.environ["DISABLE_FIREBASE_INIT"] = "true"
os.environ["FOOTBALL_API_KEY"] = "test_secret_api_key_12345"
os.environ["ALLOW_SIMULATED_ACTA"] = "false"

# Stub mínimo de Flask para ejecutar pruebas unitarias en entornos sin servidor web
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


class _FakeFirestoreSnap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class _FakeFirestoreDoc:
    def __init__(self, store, doc_id):
        self._store = store
        self._doc_id = doc_id

    def set(self, data, merge=False):
        self._store[self._doc_id] = dict(data)

    def get(self):
        return _FakeFirestoreSnap(self._store.get(self._doc_id))


class _FakeFirestoreCollection:
    def __init__(self, store):
        self._store = store

    def document(self, doc_id):
        return _FakeFirestoreDoc(self._store, doc_id)


class _FakeFirestoreDB:
    """Mock en memoria de Firestore (NO valida Firestore real con credenciales)."""
    def __init__(self):
        self.collections = {}

    def collection(self, name):
        self.collections.setdefault(name, {})
        return _FakeFirestoreCollection(self.collections[name])


class TestPhase1StrictDeliverable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flask_app = pred_app.create_app()

    def setUp(self):
        pred_app._VERIFIED_RESULTS_CACHE.clear()
        pred_app.VERIFIED_TEAM_HISTORY.clear()
        pred_app.RATINGS_REALES.clear()
        pred_app.FootballDataOrgClient._CACHE.clear()
        pred_app.FootballDataOrgClient._REQUEST_LOGS.clear()
        pred_app.MatchEnrichmentCache._STORE.clear()
        pred_app.db = None

    def _add_cache_match(self, fecha, home, away, hg, ag, comp="Premier League", code="PL"):
        pred_app._VERIFIED_RESULTS_CACHE[(fecha, home, away)] = {
            "finished": True,
            "simulado": False,
            "competicion": comp,
            "codigo_liga": code,
            "score_home": hg,
            "score_away": ag,
            "source": "football-data.org",
            "tipo_entidad": "club",
        }

    def test_01_worker_fills_cache_with_secondary_fallbacks_and_reaches_engine(self):
        """Worker usa football-data.org como primaria y SofaScore/ESPN como respaldo controlado."""
        match_data = {
            "id_partido": "pl_101",
            "local": "Arsenal",
            "visitante": "Chelsea",
            "codigo_liga": "PL",
            "liga": "Premier League",
            "fecha": "2026-11-14",
        }
        fd_payload = {
            "matches": [{
                "homeTeam": {"name": "Arsenal"},
                "awayTeam": {"name": "Chelsea"},
                "status": "FINISHED",
                "score": {"fullTime": {"home": 2, "away": 1}},
                "referees": [{"name": "Michael Oliver"}],
            }]
        }
        sofa_stats = {
            "finished": True,
            "score_home": 2,
            "score_away": 1,
            "corners_home": 6,
            "corners_away": 4,
            "corners_total": 10,
            "cards_home": 2,
            "cards_away": 2,
            "cards_total": 4,
            "shots_home": 14,
            "shots_away": 10,
            "shots_total": 24,
            "shots_on_target_home": 6,
            "shots_on_target_away": 4,
            "shots_on_target": 10,
            "referee_avg_cards": 4.2,
        }
        with patch.object(pred_app.FootballDataOrgClient, "fetch_json", return_value={"ok": True, "data": fd_payload}):
            with patch.object(pred_app.SofascoreLiveService, "fetch_match_stats", return_value=sofa_stats):
                rec = pred_app.MatchEnrichmentCache.enrich_match_worker(match_data, ttl_seconds=3600)

        self.assertTrue(rec["disponible"])
        self.assertFalse(rec["tiene_discrepancia"])
        self.assertEqual(rec["metricas"]["resultado"]["fuente"], "football-data.org")
        self.assertEqual(rec["metricas"]["corners_home"]["fuente"], "sofascore")

        out = pred_app.SportsAnalyticsEngine.generate_institutional_analysis(match_data)
        kp = out["key_probabilities"]
        self.assertFalse(kp["avg_corners"]["datos_insuficientes"])
        self.assertFalse(kp["avg_cards"]["datos_insuficientes"])
        self.assertEqual(kp["avg_cards"]["referee_name"], "Michael Oliver")
        self.assertFalse(kp["avg_shots"]["datos_insuficientes"])
        self.assertFalse(kp["avg_shots_on_target"]["datos_insuficientes"])

    def test_02_per_team_secondary_metrics_enable_only_their_market(self):
        """Métricas por equipo habilitan únicamente su mercado correspondiente sin inventar los demás."""
        match_data = {
            "id_partido": "pl_102",
            "local": "Liverpool",
            "visitante": "Everton",
            "codigo_liga": "PL",
            "liga": "Premier League",
            "fecha": "2026-11-14",
        }
        # Solo corners_home y corners_away disponibles -> solo avg_corners se habilita
        pred_app.MatchEnrichmentCache.store_observations(
            match_data,
            [{
                "fuente": "sofascore",
                "nivel_verificacion": "RESPALDO_SECUNDARIO",
                "metricas": {"corners_home": 7, "corners_away": 3},
            }],
            ttl_seconds=3600,
        )
        out_c = pred_app.SportsAnalyticsEngine.generate_institutional_analysis(match_data)
        kp_c = out_c["key_probabilities"]
        self.assertFalse(kp_c["avg_corners"]["datos_insuficientes"])
        self.assertIsNotNone(kp_c["avg_corners"]["value"])
        self.assertTrue(kp_c["avg_cards"]["datos_insuficientes"])
        self.assertTrue(kp_c["avg_shots"]["datos_insuficientes"])
        self.assertTrue(kp_c["avg_shots_on_target"]["datos_insuficientes"])

        # Habilitar tarjetas_home/away + árbitro -> solo avg_cards + avg_corners activos; tiros siguen insuficientes
        pred_app.MatchEnrichmentCache.store_observations(
            match_data,
            [{
                "fuente": "sofascore",
                "nivel_verificacion": "RESPALDO_SECUNDARIO",
                "metricas": {
                    "corners_home": 7, "corners_away": 3,
                    "tarjetas_home": 2, "tarjetas_away": 3,
                    "arbitro": "Anthony Taylor", "arbitro_avg_cards": 4.75,
                },
            }],
            ttl_seconds=3600,
        )
        out_ct = pred_app.SportsAnalyticsEngine.generate_institutional_analysis(match_data)
        kp_ct = out_ct["key_probabilities"]
        self.assertFalse(kp_ct["avg_corners"]["datos_insuficientes"])
        self.assertFalse(kp_ct["avg_cards"]["datos_insuficientes"])
        self.assertTrue(kp_ct["avg_shots"]["datos_insuficientes"])
        self.assertTrue(kp_ct["avg_shots_on_target"]["datos_insuficientes"])

        # Habilitar tiros_home/away + tiros_puerta_home/away -> todos los mercados activos
        pred_app.MatchEnrichmentCache.store_observations(
            match_data,
            [{
                "fuente": "sofascore",
                "nivel_verificacion": "RESPALDO_SECUNDARIO",
                "metricas": {
                    "corners_home": 7, "corners_away": 3,
                    "tarjetas_home": 2, "tarjetas_away": 3,
                    "arbitro": "Anthony Taylor", "arbitro_avg_cards": 4.75,
                    "tiros_home": 15, "tiros_away": 9,
                    "tiros_puerta_home": 6, "tiros_puerta_away": 3,
                },
            }],
            ttl_seconds=3600,
        )
        out_all = pred_app.SportsAnalyticsEngine.generate_institutional_analysis(match_data)
        kp_all = out_all["key_probabilities"]
        for k in ("avg_corners", "avg_cards", "avg_shots", "avg_shots_on_target"):
            self.assertFalse(kp_all[k]["datos_insuficientes"])
            self.assertIsNotNone(kp_all[k]["value"])

    def test_03_missing_expired_and_discrepant_exclude_each_market(self):
        """Expiración, discrepancia y ausencia excluyen córners, tarjetas, tiros y tiros a puerta."""
        match_data = {
            "id_partido": "pd_202",
            "local": "Real Madrid",
            "visitante": "Barcelona",
            "codigo_liga": "PD",
            "liga": "LaLiga",
            "fecha": "2026-11-14",
        }
        markets = ("avg_corners", "avg_cards", "avg_shots", "avg_shots_on_target")

        # 1. Ausentes
        out_missing = pred_app.SportsAnalyticsEngine.generate_institutional_analysis(match_data)
        for k in markets:
            self.assertTrue(out_missing["key_probabilities"][k]["datos_insuficientes"])
            self.assertIsNone(out_missing["key_probabilities"][k]["value"])
            self.assertEqual(out_missing["key_probabilities"][k]["recommended"], "Datos insuficientes")

        # 2. Expirados (ttl_seconds=-10)
        pred_app.MatchEnrichmentCache.store_observations(
            match_data,
            [{
                "fuente": "sofascore",
                "nivel_verificacion": "RESPALDO_SECUNDARIO",
                "metricas": {
                    "corners_home": 6, "corners_away": 5,
                    "tarjetas_home": 2, "tarjetas_away": 2,
                    "arbitro": "Gil Manzano", "arbitro_avg_cards": 4.9,
                    "tiros_home": 13, "tiros_away": 11,
                    "tiros_puerta_home": 5, "tiros_puerta_away": 4,
                },
            }],
            ttl_seconds=-10,
        )
        out_exp = pred_app.SportsAnalyticsEngine.generate_institutional_analysis(match_data)
        for k in markets:
            self.assertTrue(out_exp["key_probabilities"][k]["datos_insuficientes"])
            self.assertIsNone(out_exp["key_probabilities"][k]["value"])

        # 3. Discrepancia entre SofaScore y ESPN en los 4 mercados
        pred_app.MatchEnrichmentCache.store_observations(
            match_data,
            [
                {
                    "fuente": "sofascore",
                    "nivel_verificacion": "RESPALDO_SECUNDARIO",
                    "metricas": {
                        "corners_home": 6, "corners_away": 4,
                        "tarjetas_home": 2, "tarjetas_away": 2,
                        "arbitro": "Gil Manzano", "arbitro_avg_cards": 4.9,
                        "tiros_home": 13, "tiros_away": 11,
                        "tiros_puerta_home": 5, "tiros_puerta_away": 4,
                    },
                },
                {
                    "fuente": "espn",
                    "nivel_verificacion": "RESPALDO_SECUNDARIO",
                    "metricas": {
                        "corners_home": 8, "corners_away": 4,
                        "tarjetas_home": 4, "tarjetas_away": 2,
                        "arbitro": "Gil Manzano", "arbitro_avg_cards": 4.9,
                        "tiros_home": 16, "tiros_away": 11,
                        "tiros_puerta_home": 7, "tiros_puerta_away": 4,
                    },
                },
            ],
            ttl_seconds=3600,
        )
        out_disc = pred_app.SportsAnalyticsEngine.generate_institutional_analysis(match_data)
        self.assertTrue(out_disc["key_probabilities"]["_meta"]["tiene_discrepancia"])
        for k in markets:
            self.assertTrue(out_disc["key_probabilities"][k]["datos_insuficientes"])
            self.assertIsNone(out_disc["key_probabilities"][k]["value"])
            self.assertEqual(out_disc["key_probabilities"][k]["recommended"], "Datos insuficientes")

    def test_04_simulated_restart_uses_fake_firestore_persistence(self):
        """Persistencia simulada con _FakeFirestoreDB (Firestore real requiere credenciales)."""
        fake_db = _FakeFirestoreDB()
        pred_app.db = fake_db
        match_data = {
            "id_partido": "sa_303",
            "local": "Inter",
            "visitante": "Milan",
            "codigo_liga": "SA",
            "liga": "Serie A",
            "fecha": "2026-11-14",
        }
        pred_app.MatchEnrichmentCache.store_observations(
            match_data,
            [{
                "fuente": "sofascore",
                "nivel_verificacion": "RESPALDO_SECUNDARIO",
                "metricas": {"corners_home": 5, "corners_away": 5},
            }],
            ttl_seconds=3600,
        )
        # Simular reinicio limpiando la memoria _STORE
        pred_app.MatchEnrichmentCache._STORE.clear()
        self.assertEqual(len(pred_app.MatchEnrichmentCache._STORE), 0)

        out = pred_app.SportsAnalyticsEngine.generate_institutional_analysis(match_data)
        self.assertFalse(out["key_probabilities"]["avg_corners"]["datos_insuficientes"])
        self.assertIsNotNone(out["key_probabilities"]["avg_corners"]["value"])

    def test_05_obtener_pronostico_zero_external_calls(self):
        """Bloquea explícitamente requests.get, football-data.org, SofaScore, ESPN, API-Sports y worker."""
        handler = self.flask_app.routes["/obtener-pronostico"]
        espn_patch = (
            patch.object(pred_app.ESPNLiveService, "fetch_match_stats", side_effect=AssertionError("ESPN llamado!"))
            if hasattr(pred_app.ESPNLiveService, "fetch_match_stats")
            else patch.object(pred_app.ESPNLiveService, "__init__", side_effect=AssertionError("ESPN llamado!"))
        )
        with patch.object(requests, "get", side_effect=AssertionError("requests.get llamado!")), \
             patch.object(pred_app.FootballDataOrgClient, "fetch_json", side_effect=AssertionError("football-data.org llamado!")), \
             patch.object(pred_app.SofascoreLiveService, "fetch_match_stats", side_effect=AssertionError("SofaScore llamado!")), \
             espn_patch, \
             patch.object(requests.Session, "get", side_effect=AssertionError("requests.Session.get llamado!")), \
             patch.object(pred_app.ApiSportsETL, "sync_nations_league", side_effect=AssertionError("ApiSportsETL llamado!")), \
             patch.object(pred_app.MatchEnrichmentCache, "enrich_calendar_worker", side_effect=AssertionError("Worker llamado en /obtener-pronostico!")):
            resp, status_code = handler()
            self.assertEqual(status_code, 200)
            self.assertIn("destacados", resp)

    def test_06_admin_worker_isolated_from_obtener_pronostico_and_runs_only_via_admin(self):
        """Verifica que el worker administrativo existe y no se ejecuta desde /obtener-pronostico."""
        self.assertIn("/api/v1/admin/enrichment/run", self.flask_app.routes)
        with patch.object(pred_app.MatchEnrichmentCache, "enrich_match_worker") as mock_worker:
            mock_worker.return_value = {"disponible": True, "tiene_discrepancia": False}
            # /obtener-pronostico no debe disparar enrich_match_worker ni enrich_calendar_worker
            handler = self.flask_app.routes["/obtener-pronostico"]
            with patch.object(requests, "get", side_effect=AssertionError("HTTP externo prohibido")):
                resp, status_code = handler()
                self.assertEqual(status_code, 200)
            mock_worker.assert_not_called()

            # El worker solo se ejecuta cuando se invoca explícitamente
            res = pred_app.MatchEnrichmentCache.enrich_calendar_worker(target_date="2026-11-17", limit=1)
            self.assertEqual(res["procesados"], 1)
            self.assertEqual(mock_worker.call_count, 1)

    def test_07_cache_hit_without_deadlock_and_http_errors(self):
        """Dos consultas idénticas a caché responden sin deadlock; 401/403/429 sin filtrar API Key."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json.dumps({"matches": [{"id": 1}]})
        mock_resp.json.return_value = {"matches": [{"id": 1}]}
        mock_resp.headers = {"X-Requests-Available-Minute": "9", "X-RequestCounter-Reset": "60"}

        with patch.object(requests, "get", return_value=mock_resp) as mget:
            r1 = pred_app.FootballDataOrgClient.fetch_json("/competitions/PL/matches", competition_code="PL")
            r2 = pred_app.FootballDataOrgClient.fetch_json("/competitions/PL/matches", competition_code="PL")
            self.assertTrue(r1["ok"])
            self.assertFalse(r1["cache_hit"])
            self.assertTrue(r2["ok"])
            self.assertTrue(r2["cache_hit"])
            self.assertEqual(mget.call_count, 1)

        for code in (401, 403, 429):
            m_err = MagicMock()
            m_err.status_code = code
            m_err.text = "error test_secret_api_key_12345"
            m_err.headers = {}
            with patch.object(requests, "get", return_value=m_err):
                r = pred_app.FootballDataOrgClient.fetch_json(f"/competitions/PL/matches?c={code}", competition_code="PL")
                self.assertFalse(r["ok"])
                self.assertNotIn("test_secret_api_key_12345", r["error"])

    def test_08_streaks_and_no_simulated_acta_in_cache(self):
        """Rachas con 0 y 5 derrotas (0%), y ALLOW_SIMULATED_ACTA=false sin actas simuladas."""
        r0 = pred_app.SportsAnalyticsEngine.get_verified_last_5_matches("Sin Datos FC", before_date="2026-11-14", entity_type="club")
        self.assertEqual(r0["muestra_n"], 0)

        for i in range(1, 6):
            self._add_cache_match(f"2026-10-1{i}", "Valencia", f"Team{i}", 0, 2, comp="LaLiga", code="PD")
        r5 = pred_app.SportsAnalyticsEngine.get_verified_last_5_matches("Valencia", before_date="2026-11-14", entity_type="club")
        self.assertEqual(r5["streak"], "D-D-D-D-D")
        self.assertEqual(round((r5["pts"] / (r5["muestra_n"] * 3)) * 100), 0)

        self.assertFalse(pred_app.ALLOW_SIMULATED_ACTA)
        res = pred_app.obtener_resultado_real_verificado("Equipo Fake", "Otro Fake", "2026-11-10")
        self.assertFalse(res.get("finished"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
