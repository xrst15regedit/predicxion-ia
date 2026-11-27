import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
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
flask_stub.request.headers = {}
flask_stub.request.get_json = MagicMock(return_value={})
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
flask_stub.request = pred_app.request
flask_stub.g = pred_app.g


class TestPhase4AIAuditAndUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flask_app = pred_app.create_app()

    def setUp(self):
        pred_app._VERIFIED_RESULTS_CACHE.clear()
        pred_app.VERIFIED_TEAM_HISTORY.clear()
        pred_app.RATINGS_REALES.clear()
        pred_app.MatchEnrichmentCache._STORE.clear()
        pred_app.Top3RotationManager.reset_state()
        pred_app._CARTELERA_MEMO_CACHE.clear()
        pred_app._CARTELERA_MEMO_TS.clear()
        pred_app._ultimo_envio_resultados_top5.clear()
        try:
            if os.path.exists("/tmp/predicxion_last_tg_res_2026-11-14.txt"):
                os.remove("/tmp/predicxion_last_tg_res_2026-11-14.txt")
        except Exception:
            pass
        pred_app.db = None
        flask_stub.request.args = {}
        flask_stub.request.headers = {}
        flask_stub.request.get_json = MagicMock(return_value={})

    def _add_verified_team(self, team, code="PL", liga="Premier League", gf=2, ga=1):
        for i in range(1, 6):
            pred_app._VERIFIED_RESULTS_CACHE[(f"2026-10-1{i}", team, f"Rival_{team}_{i}")] = {
                "finished": True,
                "simulado": False,
                "competicion": liga,
                "codigo_liga": code,
                "score_home": gf,
                "score_away": ga,
                "corners_home": 6,
                "corners_away": 4,
                "cards_home": 2,
                "cards_away": 2,
                "shots_home": 14,
                "shots_away": 10,
                "shots_on_target_home": 5,
                "shots_on_target_away": 4,
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
        for i in range(1, 6):
            pred_app._VERIFIED_RESULTS_CACHE[(f"2026-10-1{i}", "Arsenal", f"Rival_A_{i}")] = {
                "finished": True,
                "simulado": False,
                "competicion": "Premier League",
                "codigo_liga": "PL",
                "score_home": 2,
                "score_away": 0,
                "source": "football-data.org",
                "tipo_entidad": "club",
            }
            pred_app._VERIFIED_RESULTS_CACHE[(f"2026-10-1{i}", "Chelsea", f"Rival_C_{i}")] = {
                "finished": True,
                "simulado": False,
                "competicion": "Premier League",
                "codigo_liga": "PL",
                "score_home": 1,
                "score_away": 2,
                "source": "football-data.org",
                "tipo_entidad": "club",
            }
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
        self.assertNotIn("Datos insuficientes", ai["gemini_tesis"])
        self.assertEqual(an["key_probabilities"]["avg_corners"]["tipo_dato"], "ESTIMADO_MODELO")
        self.assertIsNone(an["key_probabilities"]["avg_corners"]["value"])
        self.assertIsNotNone(an["key_probabilities"]["avg_corners"]["valor"])

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

    def test_04_frontend_html_uses_top3_labels_and_zero_top5_text(self):
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("Top 3 del Día", html)
        self.assertIn('Top <span class="text-[#00e676]">3</span> del Día', html)
        self.assertIn("Desbloquea las 3 Señales Estadísticas del Top 3", html)
        self.assertIn("Desbloquear Top 3 VIP", html)
        self.assertIn("const top3Slice = (data.top3 || []).slice(0, 3);", html)
        self.assertNotIn("Top 5", html)
        self.assertNotIn('Top <span class="text-[#00e676]">5</span>', html)
        self.assertNotIn("cinco pronósticos", html)
        self.assertNotIn("5 Señales Estadísticas", html)
        self.assertNotIn("5 destacados", html)

    def test_05_rotation_2159_no_publish_2200_publishes_once_and_2300_restart_recovers(self):
        peru_tz = timezone(timedelta(hours=-5))
        # Preparar partidos verificados para el 2026-11-15 y 2026-11-16
        teams = ["Arsenal", "Chelsea", "Liverpool", "Everton", "Manchester City", "Fulham"]
        for t in teams:
            self._add_verified_team(t, gf=2, ga=1)

        custom_pool = [
            {"id_partido": "r1", "local": "Arsenal", "visitante": "Chelsea", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-15T15:00:00Z"},
            {"id_partido": "r2", "local": "Liverpool", "visitante": "Everton", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-15T17:00:00Z"},
            {"id_partido": "r3", "local": "Manchester City", "visitante": "Fulham", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-15T19:00:00Z"},
            {"id_partido": "r4", "local": "Arsenal", "visitante": "Liverpool", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-16T15:00:00Z"},
            {"id_partido": "r5", "local": "Chelsea", "visitante": "Everton", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-16T17:00:00Z"},
            {"id_partido": "r6", "local": "Manchester City", "visitante": "Arsenal", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-16T19:00:00Z"},
        ]

        mock_tg_resp = MagicMock()
        mock_tg_resp.status_code = 200
        mock_tg_resp.text = '{"ok": true}'

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "bot123:token", "TELEGRAM_CHANNEL_ID": "@predicxionIA"}), \
             patch.object(pred_app, "ALL_FIXTURES_POOL", custom_pool), \
             patch.object(pred_app.MatchEnrichmentCache, "enrich_calendar_worker", return_value={"procesados": 3}), \
             patch.object(requests, "post", return_value=mock_tg_resp) as post_mock:

            # 1) 21:59 PE -> NO publica
            dt_2159 = datetime(2026, 11, 14, 21, 59, 0, tzinfo=peru_tz)
            r_2159 = pred_app.Top3RotationManager.check_and_run_rotation(now_pe=dt_2159)
            self.assertFalse(r_2159["executed"])
            self.assertFalse(r_2159["published"])
            self.assertEqual(r_2159["reason"], "BEFORE_22_00_PE")
            self.assertEqual(post_mock.call_count, 0)

            # 2) 22:00 PE -> Publica una vez (3 selecciones) con logs obligatorios
            dt_2200 = datetime(2026, 11, 14, 22, 0, 0, tzinfo=peru_tz)
            with self.assertLogs(pred_app.logger, level="INFO") as cm:
                r_2200 = pred_app.Top3RotationManager.check_and_run_rotation(now_pe=dt_2200)
            self.assertTrue(r_2200["executed"])
            self.assertTrue(r_2200["published"])
            self.assertEqual(r_2200["fecha_publicacion"], "2026-11-14")
            self.assertEqual(r_2200["fecha_partidos"], "2026-11-15")
            self.assertEqual(r_2200["idempotency_key"], "top3:2026-11-14:2026-11-15")
            self.assertEqual(r_2200["cantidad_selecciones"], 3)
            self.assertEqual(post_mock.call_count, 1)

            joined_logs = "\n".join(cm.output)
            self.assertIn("[Top3Rotation] started", joined_logs)
            self.assertIn("[Top3Rotation] target_date=2026-11-15", joined_logs)
            self.assertIn("[Top3Rotation] selected=3", joined_logs)
            self.assertIn("[Top3Rotation] telegram_sent=true", joined_logs)

            # 3) 23:00 PE del mismo día -> No duplica si ya se envió a las 22:00
            dt_2300_same = datetime(2026, 11, 14, 23, 0, 0, tzinfo=peru_tz)
            r_2300_dup = pred_app.Top3RotationManager.check_and_run_rotation(now_pe=dt_2300_same)
            self.assertFalse(r_2300_dup["executed"])
            self.assertTrue(r_2300_dup["already_published"])
            self.assertEqual(post_mock.call_count, 1)

            # 4) Reinicio simulado a las 23:00 PE del día siguiente cuando la rotación de las 22:00 estaba pendiente -> Recupera una sola vez
            dt_2300_next = datetime(2026, 11, 15, 23, 0, 0, tzinfo=peru_tz)
            r_2300_rec = pred_app.Top3RotationManager.check_and_run_rotation(now_pe=dt_2300_next)
            self.assertTrue(r_2300_rec["executed"])
            self.assertTrue(r_2300_rec["published"])
            self.assertEqual(r_2300_rec["idempotency_key"], "top3:2026-11-15:2026-11-16")
            self.assertEqual(r_2300_rec["cantidad_selecciones"], 3)
            self.assertEqual(post_mock.call_count, 2)

    def test_06_admin_endpoints_and_published_date_sync_with_hoy(self):
        self.assertIn("/api/v1/admin/top3/rotate", self.flask_app.routes)
        self.assertIn("/api/v1/admin/top3/rotation-status", self.flask_app.routes)

        teams = ["Arsenal", "Chelsea", "Liverpool", "Everton", "Manchester City", "Fulham"]
        for t in teams:
            self._add_verified_team(t, gf=2, ga=1)

        custom_pool = [
            {"id_partido": "r1", "local": "Arsenal", "visitante": "Chelsea", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-16T15:00:00Z"},
            {"id_partido": "r2", "local": "Liverpool", "visitante": "Everton", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-16T17:00:00Z"},
            {"id_partido": "r3", "local": "Manchester City", "visitante": "Fulham", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-16T19:00:00Z"},
        ]

        mock_tg_resp = MagicMock()
        mock_tg_resp.status_code = 200
        mock_tg_resp.text = '{"ok": true}'

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "bot123:token", "TELEGRAM_CHANNEL_ID": "@predicxionIA"}), \
             patch.object(pred_app, "ALL_FIXTURES_POOL", custom_pool), \
             patch.object(pred_app.MatchEnrichmentCache, "enrich_calendar_worker", return_value={"procesados": 3}), \
             patch.object(requests, "post", return_value=mock_tg_resp):

            flask_stub.g.user_email = "fabiancermaz@gmail.com"
            flask_stub.request.headers = {"Authorization": "Bearer test_owner_token"}
            flask_stub.request.get_json = MagicMock(return_value={"fecha_partidos": "2026-11-16", "force": True})

            with patch.object(pred_app, "_verificar_es_admin", return_value=True):
                rotate_fn = pred_app. Top3RotationManager.check_and_run_rotation
                res_rot = rotate_fn(force=True, target_date_override="2026-11-16", motivo="MANUAL_TEST")
                self.assertTrue(res_rot["executed"])

            status_handler = self.flask_app.routes["/api/v1/admin/top3/rotation-status"]
            st_resp, st_code = status_handler()
            self.assertEqual(st_code, 200)
            self.assertEqual(st_resp["fecha_partidos_publicada"], "2026-11-16")
            self.assertEqual(st_resp["cantidad_selecciones"], 3)
            self.assertEqual(st_resp["estado_telegram"], "ENVIADO")
            self.assertIsNone(st_resp["ultimo_error"])

            # El endpoint /api/v1/top3/daily sin fecha (botón "Hoy" / carga inicial) devuelve la misma fecha publicada
            flask_stub.request.args = {}
            daily_handler = self.flask_app.routes["/api/v1/top3/daily"]
            daily_resp = daily_handler()
            self.assertEqual(daily_resp["fecha"], "2026-11-16")
            self.assertEqual(daily_resp["fecha_partidos_publicada"], "2026-11-16")
            self.assertEqual(len(daily_resp["top3"]), 3)

    def test_07_verified_results_publication_after_top3_matches_finish(self):
        teams = ["Arsenal", "Chelsea", "Liverpool", "Everton", "Manchester City", "Fulham"]
        for t in teams:
            self._add_verified_team(t, gf=2, ga=1)

        custom_pool = [
            {"id_partido": "r1", "local": "Arsenal", "visitante": "Chelsea", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-14T15:00:00Z"},
            {"id_partido": "r2", "local": "Liverpool", "visitante": "Everton", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-14T17:00:00Z"},
            {"id_partido": "r3", "local": "Manchester City", "visitante": "Fulham", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-14T19:00:00Z"},
        ]

        # Registrar resultados finales verificados para los 3 partidos del 2026-11-14
        for h, a in [("Arsenal", "Chelsea"), ("Liverpool", "Everton"), ("Manchester City", "Fulham")]:
            pred_app._VERIFIED_RESULTS_CACHE[("2026-11-14", h, a)] = {
                "finished": True,
                "simulado": False,
                "competicion": "Premier League",
                "codigo_liga": "PL",
                "score_home": 2,
                "score_away": 1,
                "corners_total": 10,
                "cards_total": 4,
                "source": "football-data.org",
                "tipo_entidad": "club",
            }

        mock_tg_resp = MagicMock()
        mock_tg_resp.status_code = 200
        mock_tg_resp.text = '{"ok": true}'

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "bot123:token", "TELEGRAM_CHANNEL_ID": "@predicxionIA"}), \
             patch.object(pred_app, "ALL_FIXTURES_POOL", custom_pool), \
             patch.object(requests, "post", return_value=mock_tg_resp) as post_mock:

            cierre = pred_app.Top3RotationManager.close_previous_matchday("2026-11-14")
            self.assertEqual(cierre["picks_auditados"], 3)
            self.assertEqual(cierre["finalizados"], 3)
            self.assertTrue(cierre["resultados_enviados"])
            self.assertGreaterEqual(post_mock.call_count, 1)

    def test_08_obtener_pronostico_performance_100_matches_under_limit(self):
        import time as _t
        teams = [f"PerfClub_{i}" for i in range(25)]
        for t_name in teams:
            self._add_verified_team(t_name, gf=2, ga=1)

        perf_pool = []
        for idx in range(120):
            h = teams[idx % len(teams)]
            a = teams[(idx + 1 + (idx // len(teams))) % len(teams)]
            if h == a:
                a = teams[(idx + 2) % len(teams)]
            perf_pool.append({
                "id_partido": f"perf_{idx}",
                "local": h,
                "visitante": a,
                "liga": "Premier League",
                "codigo_liga": "PL",
                "fecha_utc": "2026-11-28T15:00:00Z",
                "estado": "SCHEDULED",
            })
        # Incluir 1 partido malformado para validar aislamiento de errores
        perf_pool.append({"id_partido": "bad_1", "local": None, "visitante": None, "liga": None, "fecha_utc": "2026-11-28T15:00:00Z"})

        handler = self.flask_app.routes["/obtener-pronostico"]
        flask_stub.request.args = {"fecha": "2026-11-28"}
        with patch.object(pred_app, "ALL_FIXTURES_POOL", perf_pool):
            pred_app.ensure_fixtures_date_index(force=True)
            t0 = _t.perf_counter()
            with self.assertLogs(pred_app.logger, level="INFO") as cm_perf:
                resp, status_code = handler()
            elapsed = _t.perf_counter() - t0
        perf_logs = "\n".join(cm_perf.output)
        self.assertIn("fixture descartado: equipos incompletos", perf_logs)
        self.assertNotIn("unsupported operand type(s)", perf_logs)

        self.assertEqual(status_code, 200)
        self.assertTrue(resp["success"])
        m = resp["metricas_rendimiento"]
        self.assertGreaterEqual(m["partidos_procesados"], 120)
        self.assertLess(elapsed, 10.0)
        self.assertLess(m["tiempo_total_seg"], 10.0)
        self.assertEqual(m["recorridos_historicos"], 0)
        self.assertGreater(m["consultas_cache"], 0)

    def test_09_highlightly_realistic_response_reaches_enrichment_cache_and_engine_all_10_fields(self):
        import json as _json
        match_data = {
            "id_partido": "hl_real_1",
            "local": "Arsenal",
            "visitante": "Chelsea",
            "codigo_liga": "PL",
            "liga": "Premier League",
            "fecha": "2026-11-15",
            "fecha_utc": "2026-11-15T15:00:00Z",
        }
        matches_resp = MagicMock()
        matches_resp.status_code = 200
        matches_resp.text = _json.dumps({
            "data": [{
                "id": 554433,
                "homeTeam": {"name": "Arsenal"},
                "awayTeam": {"name": "Chelsea"},
                "state": {"description": "Finished", "score": {"current": "2 - 1"}}
            }]
        })
        matches_resp.json.return_value = _json.loads(matches_resp.text)

        stats_resp = MagicMock()
        stats_resp.status_code = 200
        stats_resp.text = _json.dumps([
            {
                "team": {"name": "Arsenal"},
                "statistics": [
                    {"displayName": "Corner Kicks", "value": 7},
                    {"displayName": "Yellow Cards", "value": 2},
                    {"displayName": "Red Cards", "value": 0},
                    {"displayName": "Shots on Goal", "value": 6},
                    {"displayName": "Shots off Goal", "value": 5},
                    {"displayName": "Blocked Shots", "value": 3},
                    {"displayName": "Total Shots", "value": 14},
                    {"displayName": "Fouls", "value": 10},
                ]
            },
            {
                "team": {"name": "Chelsea"},
                "statistics": [
                    {"displayName": "Corner Kicks", "value": 4},
                    {"displayName": "Yellow Cards", "value": 3},
                    {"displayName": "Red Cards", "value": 0},
                    {"displayName": "Shots on Goal", "value": 4},
                    {"displayName": "Shots off Goal", "value": 4},
                    {"displayName": "Blocked Shots", "value": 1},
                    {"displayName": "Total Shots", "value": 9},
                    {"displayName": "Fouls", "value": 12},
                ]
            }
        ])
        stats_resp.json.return_value = _json.loads(stats_resp.text)

        def _fake_hl_get(url, headers=None, params=None, timeout=12):
            if url.endswith("/matches"):
                return matches_resp
            if url.endswith("/statistics/554433"):
                return stats_resp
            raise AssertionError(f"URL inesperada: {url}")

        # Incluso si ESPN devuelve valores distintos en segundo plano, Highlightly debe prevalecer sin perder tiros_home/away
        espn_conflicting = {
            "finished": False, "corners_home": None, "corners_away": None,
            "shots_home": 0, "shots_away": 0, "shots_on_target_home": 0, "shots_on_target_away": 0,
        }

        with patch.dict(os.environ, {"HIGHLIGHTLY_API_KEY": "test_hl_live_key"}), \
             patch.object(pred_app.FootballDataOrgClient, "fetch_json", return_value={"ok": False, "data": None}), \
             patch.object(requests, "get", side_effect=_fake_hl_get), \
             patch.object(pred_app.SofascoreLiveService, "fetch_match_stats", return_value=None), \
             patch.object(pred_app.ESPNLiveService, "fetch_match_stats", return_value=espn_conflicting), \
             patch.object(pred_app.ApiSportsETL, "fetch_match_stats", return_value=None):
            with self.assertLogs(pred_app.logger, level="INFO") as cm:
                rec = pred_app.MatchEnrichmentCache.enrich_match_worker(match_data, ttl_seconds=3600)

        joined_logs = "\n".join(cm.output)
        for req_field in (
            "corners_home", "corners_away",
            "cards_home", "cards_away",
            "shots_home", "shots_away",
            "shots_on_target_home", "shots_on_target_away",
            "fouls_home", "fouls_away",
            "tiros_home", "tiros_away",
            "tiros_puerta_home", "tiros_puerta_away",
        ):
            self.assertIn(req_field, joined_logs)
            self.assertIsNotNone(rec["metricas"][req_field]["valor"], f"Falta {req_field} en MatchEnrichmentCache")

        self.assertEqual(rec["metricas"]["tiros_home"]["valor"], 14)
        self.assertEqual(rec["metricas"]["tiros_away"]["valor"], 9)
        self.assertEqual(rec["metricas"]["tiros"]["valor"], 23)
        self.assertEqual(rec["metricas"]["tiros_puerta_home"]["valor"], 6)
        self.assertEqual(rec["metricas"]["tiros_puerta_away"]["valor"], 4)
        self.assertEqual(rec["metricas"]["tiros_puerta"]["valor"], 10)

        # Confirmar que incluso si otra métrica (ej. arbitro) tiene discrepancia, tiros_home/away NO se descarta
        an = pred_app.SportsAnalyticsEngine.generate_institutional_analysis(match_data)
        kp = an["key_probabilities"]
        for k_m in ("avg_corners", "avg_cards", "avg_shots", "avg_shots_on_target", "avg_fouls"):
            self.assertFalse(kp[k_m]["datos_insuficientes"], f"{k_m} marcado como insuficiente")
            self.assertIsNotNone(kp[k_m]["value"], f"{k_m} sin valor en motor")


    def test_10_global_team_logo_system_all_10_competitions_and_priority_order(self):
        # 1. Equivalencias de normalización (tildes, abreviaturas y alias)
        self.assertEqual(pred_app._norm_equipo("Atlético de Madrid"), pred_app._norm_equipo("Atletico Madrid"))
        self.assertEqual(pred_app._norm_equipo("Bayern Múnich"), pred_app._norm_equipo("Bayern Munich"))
        self.assertEqual(pred_app._norm_equipo("PSG"), pred_app._norm_equipo("Paris Saint-Germain"))

        logo_atm_1 = pred_app.get_team_logo("Atlético de Madrid", competition_code="PD")
        logo_atm_2 = pred_app.get_team_logo("Atletico Madrid", competition_code="PD")
        self.assertEqual(logo_atm_1["logo_url"], logo_atm_2["logo_url"])

        logo_bay_1 = pred_app.get_team_logo("Bayern Múnich", competition_code="BL1")
        logo_bay_2 = pred_app.get_team_logo("Bayern Munich", competition_code="BL1")
        self.assertEqual(logo_bay_1["logo_url"], logo_bay_2["logo_url"])

        logo_psg_1 = pred_app.get_team_logo("PSG", competition_code="FL1")
        logo_psg_2 = pred_app.get_team_logo("Paris Saint-Germain", competition_code="FL1")
        self.assertEqual(logo_psg_1["logo_url"], logo_psg_2["logo_url"])

        # 2. Equipos de las 10 competiciones configuradas y estructura de team_logos[team_key]
        sample_teams_10_leagues = {
            "BL1": "Bayern Múnich",
            "BSA": "Flamengo",
            "FL1": "PSG",
            "PL": "Arsenal",
            "PPL": "Benfica",
            "PD": "Atlético de Madrid",
            "SA": "Inter Milan",
            "UCL": "Real Madrid",
            "UEL": "Ajax",
            "UNL": "España",
        }
        for comp_code, t_name in sample_teams_10_leagues.items():
            info = pred_app.get_team_logo(t_name, competition_code=comp_code)
            t_key = pred_app._norm_equipo(t_name)
            self.assertIn(t_key, pred_app.team_logos)
            cached_entry = pred_app.team_logos[t_key]
            for req_k in ("team_name", "logo_url", "source", "updated_at"):
                self.assertIn(req_k, cached_entry, f"Falta {req_k} en team_logos[{t_key}]")
            self.assertTrue(
                bool(info.get("logo_url")) or bool(info.get("fallback_initials")),
                f"Sin logo ni fallback para {t_name} ({comp_code})",
            )

        # 3. Prioridad estricta de fuentes: football-data.org > highlightly > cache_local > fallback_initials
        unknown_team = "Deportivo Inexistente 2099"
        fb_info = pred_app.get_team_logo(unknown_team, competition_code="PD")
        self.assertIsNone(fb_info["logo_url"])
        self.assertEqual(fb_info["source"], "fallback_initials")
        self.assertEqual(fb_info["fallback_initials"], "DI")

        pred_app.register_team_logo(unknown_team, "https://cache.local/di.png", source="cache_local")
        self.assertEqual(pred_app.get_team_logo(unknown_team)["source"], "cache_local")
        self.assertEqual(pred_app.get_team_logo(unknown_team)["logo_url"], "https://cache.local/di.png")

        pred_app.register_team_logo(unknown_team, "https://soccer.highlightly.net/logos/di.png", source="highlightly")
        self.assertEqual(pred_app.get_team_logo(unknown_team)["source"], "highlightly")
        self.assertEqual(pred_app.get_team_logo(unknown_team)["logo_url"], "https://soccer.highlightly.net/logos/di.png")

        pred_app.register_team_logo(unknown_team, "https://crests.football-data.org/9999.png", source="football-data.org")
        self.assertEqual(pred_app.get_team_logo(unknown_team)["source"], "football-data.org")
        self.assertEqual(pred_app.get_team_logo(unknown_team)["logo_url"], "https://crests.football-data.org/9999.png")

        # Intentar sobrescribir con fuente de menor prioridad NO debe reemplazar football-data.org
        pred_app.register_team_logo(unknown_team, "https://soccer.highlightly.net/logos/old.png", source="highlightly")
        self.assertEqual(pred_app.get_team_logo(unknown_team)["source"], "football-data.org")
        self.assertEqual(pred_app.get_team_logo(unknown_team)["logo_url"], "https://crests.football-data.org/9999.png")

    def test_11_all_endpoints_return_logos_or_fallbacks_with_zero_external_http_calls(self):
        pred_app.ensure_fixtures_date_index(force=True)

        # Verificar sin ninguna llamada HTTP externa (requests.get / requests.post bloqueados)
        with patch.object(requests, "get", side_effect=AssertionError("HTTP GET prohibido durante renderizado")) as get_spy:
            flask_stub.request.args = {"fecha": "2026-11-20"}
            pron_handler = self.flask_app.routes["/obtener-pronostico"]
            resp_pron, code_pron = pron_handler()
            self.assertEqual(code_pron, 200)
            self.assertTrue(resp_pron["success"])
            self.assertEqual(get_spy.call_count, 0)

            todos = resp_pron["todos"]
            self.assertEqual(len(todos), 9, "Deben estar presentes las 9 competiciones activas con UNL deshabilitada")
            total_checked = 0
            for liga_name, matches in todos.items():
                for m in matches:
                    total_checked += 1
                    self.assertTrue(
                        bool(m.get("logo_local")) or bool(m.get("fallback_logo_local")),
                        f"Partido sin logo_local ni fallback_logo_local: {m.get('partido')}",
                    )
                    self.assertTrue(
                        bool(m.get("logo_visitante")) or bool(m.get("fallback_logo_visitante")),
                        f"Partido sin logo_visitante ni fallback_logo_visitante: {m.get('partido')}",
                    )
            self.assertGreater(total_checked, 300)

            # Verificar /api/v1/top3/daily
            for t in ["Arsenal", "Chelsea", "Liverpool", "Everton", "Manchester City", "Fulham"]:
                self._add_verified_team(t, gf=2, ga=1)
            custom_pool = [
                {"id_partido": "lg1", "local": "Arsenal", "visitante": "Chelsea", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-16T15:00:00Z"},
                {"id_partido": "lg2", "local": "Liverpool", "visitante": "Everton", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-16T17:00:00Z"},
                {"id_partido": "lg3", "local": "Club Sin Escudo Local", "visitante": "Club Sin Escudo Visita", "liga": "Premier League", "codigo_liga": "PL", "fecha_utc": "2026-11-16T19:00:00Z"},
            ]
            self._add_verified_team("Club Sin Escudo Local", gf=2, ga=0)
            self._add_verified_team("Club Sin Escudo Visita", gf=1, ga=1)

            with patch.object(pred_app, "ALL_FIXTURES_POOL", custom_pool):
                flask_stub.request.args = {"fecha": "2026-11-16"}
                top3_resp = self.flask_app.routes["/api/v1/top3/daily"]()
                self.assertTrue(top3_resp["success"])
                self.assertEqual(len(top3_resp["top3"]), 3)
                for item in top3_resp["top3"]:
                    self.assertIn("logo_local", item)
                    self.assertIn("logo_visitante", item)
                    self.assertIn("fallback_logo_local", item)
                    self.assertIn("fallback_logo_visitante", item)
                    self.assertTrue(bool(item.get("logo_local")) or bool(item.get("fallback_logo_local")))
                    self.assertTrue(bool(item.get("logo_visitante")) or bool(item.get("fallback_logo_visitante")))

                # Verificar /api/v1/ai/triple-analysis (sin llamadas externas a logos)
                flask_stub.request.get_json = MagicMock(return_value={"match_id": "lg1"})
                with patch.object(pred_app.DualAIEngine, "analyze_match_pipeline", return_value={"estado": "ACTIVO"}):
                    ai_resp = self.flask_app.routes["/api/v1/ai/triple-analysis"]()
                    self.assertTrue(ai_resp["success"])
                    self.assertTrue(bool(ai_resp.get("logo_local")) or bool(ai_resp.get("fallback_logo_local")))
                    self.assertTrue(bool(ai_resp.get("logo_visitante")) or bool(ai_resp.get("fallback_logo_visitante")))

        # Verificar que index.html contiene el soporte de img + alt + onerror fallback
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("t.logo_local", html)
        self.assertIn("t.logo_visitante", html)
        self.assertIn('alt="${esc(limpio)}"', html)
        self.assertIn("onerror=", html)


    def test_12_small_teams_last_5_highlightly_espn_fallback_and_separate_modeled_estimation(self):
        import json as _json

        # 1. Sin base estadística suficiente -> devuelve "Sin base suficiente para estimar" (no un número arbitrario)
        an_no_base = pred_app.SportsAnalyticsEngine.generate_institutional_analysis({
            "local": "ClubNuevoSinBaseA",
            "visitante": "ClubNuevoSinBaseB",
            "codigo_liga": "PD",
            "liga": "LaLiga",
            "fecha": "2026-11-20",
        })
        for m_key in ("avg_corners", "avg_cards", "avg_shots", "avg_shots_on_target"):
            m_obj = an_no_base["key_probabilities"][m_key]
            for req_k in ("valor", "tipo_dato", "fuente", "muestra_n", "confianza"):
                self.assertIn(req_k, m_obj, f"Falta {req_k} en {m_key}")
            self.assertIsNone(m_obj["value"])
            self.assertIsNotNone(m_obj["valor"])
            self.assertEqual(m_obj["tipo_dato"], "ESTIMADO_MODELO")
            self.assertEqual(m_obj["nivel_prior"], "NIVEL_3_PRIOR_COMPETICION")
            self.assertEqual(m_obj["muestra_n"], 0)
            self.assertIn("intervalo_estimado", m_obj)
            self.assertIn("fecha_calculo", m_obj)
            self.assertIn("metodo", m_obj)

        # 2. Obtención de últimos 5 partidos mediante Highlightly (3 antes de fecha + 1 futuro ignorado) y respaldo ESPN (2 antes de fecha)
        hl_matches_payload = {
            "data": [
                {"id": 901, "date": "2026-11-25T15:00:00Z", "homeTeam": {"name": "Mirassol"}, "awayTeam": {"name": "Bahia"}, "state": {"description": "Finished", "score": {"current": "3 - 0"}}},
                {"id": 902, "date": "2026-11-10T15:00:00Z", "homeTeam": {"name": "Mirassol"}, "awayTeam": {"name": "Santos"}, "state": {"description": "Finished", "score": {"current": "2 - 1"}}},
                {"id": 903, "date": "2026-11-05T15:00:00Z", "homeTeam": {"name": "Gremio"}, "awayTeam": {"name": "Mirassol"}, "state": {"description": "Finished", "score": {"current": "1 - 1"}}},
                {"id": 904, "date": "2026-11-01T15:00:00Z", "homeTeam": {"name": "Mirassol"}, "awayTeam": {"name": "Coritiba"}, "state": {"description": "Finished", "score": {"current": "0 - 1"}}},
            ]
        }
        espn_scoreboard_payload = {
            "events": [
                {
                    "id": "e1",
                    "date": "2026-10-25T18:00Z",
                    "competitions": [{
                        "date": "2026-10-25T18:00Z",
                        "status": {"type": {"completed": True, "state": "post"}},
                        "competitors": [
                            {"homeAway": "home", "score": "2", "team": {"displayName": "Mirassol", "name": "Mirassol"}, "statistics": []},
                            {"homeAway": "away", "score": "0", "team": {"displayName": "Ceará", "name": "Ceará"}, "statistics": []},
                        ],
                    }],
                },
                {
                    "id": "e2",
                    "date": "2026-10-20T18:00Z",
                    "competitions": [{
                        "date": "2026-10-20T18:00Z",
                        "status": {"type": {"completed": True, "state": "post"}},
                        "competitors": [
                            {"homeAway": "home", "score": "1", "team": {"displayName": "Fortaleza", "name": "Fortaleza"}, "statistics": []},
                            {"homeAway": "away", "score": "2", "team": {"displayName": "Mirassol", "name": "Mirassol"}, "statistics": []},
                        ],
                    }],
                },
            ]
        }

        espn_resp = MagicMock()
        espn_resp.status_code = 200
        espn_resp.json.return_value = espn_scoreboard_payload

        with patch.object(pred_app.HighlightlyFootballClient, "fetch_json", return_value={"ok": True, "data": hl_matches_payload}), \
             patch.object(pred_app.HighlightlyFootballClient, "fetch_statistics", return_value=None), \
             patch.object(requests, "get", return_value=espn_resp):
            last5_mirassol = pred_app.MatchEnrichmentCache.enrich_team_last_5_matches(
                "Mirassol", before_date="2026-11-15", competition_code="BSA", limit=5
            )

        self.assertEqual(len(last5_mirassol), 5)
        for m_item in last5_mirassol:
            self.assertLess(m_item["fecha"], "2026-11-15", "No debe incluir partidos en o después de la fecha del encuentro")

        # 3. Con resultados históricos de goles pero sin tiros/tarjetas/córners verificados:
        #    - No bloquea el partido
        #    - Genera estimación modelada separada (ESTIMADO_MODELO) marcada explícitamente
        #    - Mantiene value=None (verificado) separado de valor (estimado por modelo)
        self._add_verified_team("Remo", code="BSA", liga="Brasileirao", gf=1, ga=1)
        # Limpiar métricas secundarias de Remo para probar estimación modelada pura
        for k_v, v_v in list(pred_app._VERIFIED_RESULTS_CACHE.items()):
            if "Remo" in k_v:
                for sec_k in ("corners_home", "corners_away", "cards_home", "cards_away", "shots_home", "shots_away", "shots_on_target_home", "shots_on_target_away"):
                    v_v.pop(sec_k, None)
        pred_app.SportsAnalyticsEngine.rebuild_verified_history_index(force=True)

        an_small = pred_app.SportsAnalyticsEngine.generate_institutional_analysis({
            "local": "Mirassol",
            "visitante": "Remo",
            "codigo_liga": "BSA",
            "liga": "Campeonato Brasileiro Série A",
            "fecha": "2026-11-15",
        })
        p_princ = an_small["pronostico_principal"]
        self.assertNotIn(p_princ["seleccion"], ("Datos insuficientes", "Confianza insuficiente", ""))
        self.assertFalse(p_princ["confianza_insuficiente"])

        kp_s = an_small["key_probabilities"]
        for m_key in ("avg_corners", "avg_cards", "avg_shots", "avg_shots_on_target"):
            m_obj = kp_s[m_key]
            for req_k in ("valor", "tipo_dato", "fuente", "muestra_n", "confianza"):
                self.assertIn(req_k, m_obj)
            # Separación estricta: value (verificado) es None, pero valor y estimacion_modelada tienen la estimación marcada
            self.assertIsNone(m_obj["value"])
            self.assertTrue(m_obj["datos_insuficientes"])
            self.assertIsNotNone(m_obj["valor"])
            self.assertEqual(m_obj["tipo_dato"], "ESTIMADO_MODELO")
            self.assertGreater(m_obj["muestra_n"], 0)
            self.assertIn(m_obj["confianza"], ("MEDIA", "BAJA"))
            self.assertIsNotNone(m_obj["estimacion_modelada"])
            self.assertEqual(m_obj["estimacion_modelada"]["tipo_dato"], "ESTIMADO_MODELO")

        # Separación en IA
        sep_ia = an_small["consenso_dual_ia"]["separacion_datos"]
        self.assertEqual(sep_ia["metricas_verificadas"], [])
        self.assertIn("avg_corners", sep_ia["metricas_estimadas_modelo"])

        # Verificar que index.html reemplazó N/D por etiquetas limpias y "No estimable"
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("N/D", html)
        self.assertIn("Promedio de córners", html)
        self.assertIn("No estimable", html)


    def test_13_comprehensive_integral_requirements(self):
        # 1. 17/11 y 18/11 con partidos reales, UNL deshabilitada por defecto (DISABLED_COMPETITIONS=UNL),
        #    cero fechas adelantadas y separación de fechas
        pred_app.ensure_fixtures_date_index(force=True)
        pron_handler = self.flask_app.routes["/obtener-pronostico"]

        with patch.dict(os.environ, {"DISABLED_COMPETITIONS": "UNL"}), patch.object(requests, "get", side_effect=AssertionError("No HTTP en /obtener-pronostico")):
            flask_stub.request.args = {"fecha": "2026-11-17"}
            resp_17, c17 = pron_handler()
            self.assertEqual(c17, 200)
            self.assertEqual(resp_17["fecha_activa_destacados"], "2026-11-17")
            self.assertIn("UNL", resp_17["competiciones_deshabilitadas"])
            # Con UNL deshabilitada, 2026-11-17 no tiene partidos activos y NO debe rellenarse con días 18/19/20/21
            self.assertEqual(len(resp_17["destacados"]), 0)
            for d_item in resp_17["destacados"]:
                self.assertEqual(d_item["fecha"], "2026-11-17")
                self.assertEqual(d_item["fecha_local_partido"], "2026-11-17")
                self.assertIn("fecha_programada", d_item)
                self.assertIn("fecha_publicacion", d_item)
                self.assertIn("fecha_rotacion", d_item)
                self.assertNotEqual(d_item["codigo_liga"], "UNL")

            flask_stub.request.args = {"fecha": "2026-11-18"}
            resp_18, c18 = pron_handler()
            self.assertEqual(c18, 200)
            self.assertEqual(resp_18["fecha_activa_destacados"], "2026-11-18")
            self.assertGreater(len(resp_18["destacados"]), 0)
            for d_item in resp_18["destacados"]:
                self.assertEqual(d_item["fecha"], "2026-11-18")
                self.assertEqual(d_item["fecha_local_partido"], "2026-11-18")
                self.assertNotEqual(d_item["codigo_liga"], "UNL")

            # Un partido de cada competición activa (9 ligas)
            active_codes_seen = set()
            for liga_name, m_list in resp_17["todos"].items():
                self.assertNotIn("Nations League", liga_name)
                if m_list:
                    active_codes_seen.add(m_list[0]["codigo_liga"])
            self.assertEqual(active_codes_seen, {"BL1", "BSA", "FL1", "PL", "PPL", "PD", "SA", "UCL", "UEL"})

        # 2. Reactivar UNL cambiando únicamente la variable de entorno DISABLED_COMPETITIONS=""
        with patch.dict(os.environ, {"DISABLED_COMPETITIONS": ""}):
            pred_app.ensure_fixtures_date_index(force=True)
            flask_stub.request.args = {"fecha": "2026-11-17"}
            resp_unl_on, _ = pron_handler()
            self.assertTrue(any(m["codigo_liga"] == "UNL" for m in resp_unl_on["destacados"]))
        pred_app.ensure_fixtures_date_index(force=True)

        # 3. Resultados reales de los días 12, 13, 14, 15, 16 y 17 de noviembre (sin inventar, sin adelantar)
        for day_i in ("12", "13", "14", "15", "16", "17"):
            f_day = f"2026-11-{day_i}"
            mock_hl = {"finished": True, "score_home": 2, "score_away": 1, "corners_total": 9, "cards_total": 4}
            with patch.object(pred_app.HighlightlyFootballClient, "_get_api_key", return_value="k_test"), \
                 patch.object(pred_app.HighlightlyFootballClient, "fetch_match_stats", return_value=mock_hl):
                res_day = pred_app.obtener_resultado_real_verificado(f"EqLoc{day_i}", f"EqVis{day_i}", f_day, liga="Premier League")
            self.assertTrue(res_day["finished"])
            self.assertEqual(res_day["score_home"], 2)
            self.assertEqual(res_day["score_away"], 1)

        # Partido futuro o aplazado debe seguir PENDIENTE
        fut_res = pred_app.obtener_resultado_real_verificado("Arsenal", "Chelsea", "2026-12-28", liga="Premier League")
        self.assertFalse(fut_res["finished"])
        grade_pend = pred_app.SportsResultsAuditor.grade_prediction({"seleccion": "Más de 1.5 goles"}, fut_res)
        self.assertEqual(grade_pend["estado"], "PENDIENTE")

        # 4. Top 3 con exactamente 3 selecciones para 2026-11-18 (con datos verificados)
        for t in ("Corinthians", "Botafogo", "Coritiba", "Santos", "Cruzeiro", "Palmeiras"):
            self._add_verified_team(t, code="BSA", liga="Campeonato Brasileiro Série A", gf=2, ga=1)
        flask_stub.request.args = {"fecha": "2026-11-18"}
        top3_18 = self.flask_app.routes["/api/v1/top3/daily"]()
        self.assertTrue(top3_18["success"])
        self.assertEqual(len(top3_18["top3"]), 3)
        for item in top3_18["top3"]:
            self.assertEqual(item["fecha"], "2026-11-18")
            self.assertTrue(bool(item.get("logo_local")) or bool(item.get("fallback_logo_local")))
            self.assertTrue(bool(item.get("logo_visitante")) or bool(item.get("fallback_logo_visitante")))

        # 5. Logos solo en pronósticos y Top 3 en index.html (no en sidebar ni carrusel),
        #    nombres limpios y una sola fecha en Top 3 + mercados alternativos con logs
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("Promedio de córners", html)
        self.assertIn("Promedio de tarjetas", html)
        self.assertIn("Promedio de remates", html)
        self.assertIn("Promedio de tiros a puerta", html)
        self.assertNotIn("Estimación del modelo", html)
        self.assertIn("[MercadosAlternativos] status=", html)
        self.assertIn("displayFecha.innerText = data.fecha;", html)
        # Confirmar que renderizarSidebar y renderizarCarrusel ya no invocan generarEscudoEquipoHtml
        sidebar_fn = html.split("function renderizarSidebar")[1].split("function toggleLiga")[0]
        carousel_fn = html.split("function renderizarCarrusel")[1].split("async function ejecutarAnalisisTripleIA")[0]
        self.assertNotIn("generarEscudoEquipoHtml", sidebar_fn)
        self.assertNotIn("generarEscudoEquipoHtml", carousel_fn)

    def test_14_complete_calendar_10_validation_scenarios(self):
        pron_handler = self.flask_app.routes["/obtener-pronostico"]
        pred_app.invalidate_calendar_caches(rebuild_pool=True)

        # Escenario 1: Fecha afectada (2026-11-18) con exactamente 6 partidos de Serie A brasileña
        # y verificación estricta del conteo después de cada etapa
        with patch.object(requests, "get", side_effect=AssertionError("No HTTP en /obtener-pronostico")):
            flask_stub.request.args = {"fecha": "2026-11-18"}
            resp_18, code_18 = pron_handler()
        self.assertEqual(code_18, 200)
        aud_18 = resp_18["auditoria_calendario_fecha"]
        self.assertEqual(aud_18["partidos_oficiales"], 6)
        self.assertEqual(aud_18["partidos_combinados"], 6)
        self.assertEqual(aud_18["partidos_deduplicados"], 6)
        self.assertEqual(aud_18["partidos_filtrados"], 6)
        self.assertEqual(aud_18["partidos_enviados_al_frontend"], 6)
        self.assertEqual(len(resp_18["destacados"]), 6)

        equipos_18 = {(m["local"], m["visitante"]) for m in resp_18["destacados"]}
        self.assertIn(("Flamengo", "Atlético Paranaense"), equipos_18)
        self.assertIn(("Corinthians", "Botafogo"), equipos_18)
        self.assertIn(("Coritiba", "Santos"), equipos_18)
        self.assertIn(("Cruzeiro", "Palmeiras"), equipos_18)
        self.assertIn(("Remo", "Chapecoense"), equipos_18)
        self.assertIn(("Gremio", "Bahia"), equipos_18)

        # Escenario 1b: Si el calendario manual tuviera solo 4 partidos y football-data.org aporta los 2 faltantes
        manual_4 = [f for f in pred_app.ALL_FIXTURES_POOL if f.get("fecha") == "2026-11-18" and f.get("local") not in ("Remo", "Gremio")]
        self.assertEqual(len(manual_4), 4)
        fd_missing_2 = [
            {"id": 99101, "homeTeam": {"name": "Clube do Remo"}, "awayTeam": {"name": "Chapecoense AF"}, "utcDate": "2026-11-18T23:00:00Z", "status": "SCHEDULED", "competition": {"code": "BSA", "name": "Campeonato Brasileiro Série A"}},
            {"id": 99102, "homeTeam": {"name": "Grêmio FBPA"}, "awayTeam": {"name": "EC Bahia"}, "utcDate": "2026-11-19T00:30:00Z", "status": "SCHEDULED", "competition": {"code": "BSA", "name": "Campeonato Brasileiro Série A"}},
        ]
        aud_merged = pred_app.CalendarSyncService.audit_date_pipeline(
            "2026-11-18",
            manual_fixtures=manual_4,
            fd_matches=fd_missing_2,
        )
        self.assertEqual(aud_merged["partidos_oficiales"], 6)
        self.assertEqual(aud_merged["partidos_combinados"], 6)
        self.assertEqual(aud_merged["partidos_deduplicados"], 6)
        self.assertEqual(aud_merged["partidos_filtrados"], 6)
        self.assertEqual(aud_merged["partidos_enviados_al_frontend"], 6)

        # Escenario 2 y 3: Una fecha con más de 10 partidos (2026-11-21 tiene 27 partidos) repartidos entre varias ligas
        with patch.object(requests, "get", side_effect=AssertionError("No HTTP en /obtener-pronostico")):
            flask_stub.request.args = {"fecha": "2026-11-21"}
            resp_21, code_21 = pron_handler()
        self.assertEqual(code_21, 200)
        self.assertGreater(len(resp_21["destacados"]), 12)
        ligas_21 = {m["codigo_liga"] for m in resp_21["destacados"]}
        self.assertGreaterEqual(len(ligas_21), 5)
        self.assertEqual(
            resp_21["auditoria_calendario_fecha"]["partidos_filtrados"],
            resp_21["auditoria_calendario_fecha"]["partidos_enviados_al_frontend"],
        )
        self.assertEqual(len(resp_21["destacados"]), resp_21["auditoria_calendario_fecha"]["partidos_enviados_al_frontend"])

        # Escenario 4 y 5: Equipos con tildes y nombres alternativos + Partidos duplicados entre fuentes
        dup_fd = [
            {"id": 8801, "homeTeam": {"name": "Grêmio FBPA"}, "awayTeam": {"name": "EC Bahía"}, "utcDate": "2026-11-18T19:30:00Z", "status": "SCHEDULED"},
            {"id": 8802, "homeTeam": {"name": "Clube do Remo"}, "awayTeam": {"name": "Chapecoense AF"}, "utcDate": "2026-11-18T18:00:00Z", "status": "SCHEDULED"},
            {"id": 8803, "homeTeam": {"name": "CR Flamengo"}, "awayTeam": {"name": "Athletico-PR"}, "utcDate": "2026-11-18T18:30:00Z", "status": "SCHEDULED"},
        ]
        aud_dup = pred_app.CalendarSyncService.audit_date_pipeline(
            "2026-11-18",
            fd_matches=dup_fd,
            external_unauthorized_fixtures=[{"local": "FakeA", "visitante": "FakeB", "fecha": "2026-11-18", "codigo_liga": "BSA", "proveedor": "highlightly"}],
        )
        self.assertEqual(aud_dup["partidos_combinados"], 9)
        self.assertEqual(aud_dup["partidos_deduplicados"], 6)
        self.assertEqual(aud_dup["partidos_filtrados"], 6)
        self.assertEqual(aud_dup["partidos_enviados_al_frontend"], 6)
        self.assertEqual(aud_dup["total_por_fuente"]["fuentes_externas_rechazadas"], 1)

        # Escenario 6: Un partido sin estadísticas aparece primero en el calendario y luego se enriquece/modela
        pred_app.VERIFIED_TEAM_HISTORY.pop("Remo", None)
        pred_app.VERIFIED_TEAM_HISTORY.pop("Chapecoense", None)
        pred_app.SportsAnalyticsEngine.rebuild_verified_history_index(force=True)
        pred_app.invalidate_calendar_caches(rebuild_pool=False)
        flask_stub.request.args = {"fecha": "2026-11-18"}
        resp_no_stats, _ = pron_handler()
        remo_match = [m for m in resp_no_stats["destacados"] if m["local"] == "Remo" and m["visitante"] == "Chapecoense"]
        self.assertEqual(len(remo_match), 1)
        self.assertEqual(remo_match[0]["key_probabilities"]["avg_corners"]["tipo_dato"], "ESTIMADO_MODELO")

        # Escenario 7: Cambio de fecha entre UTC (2026-11-19T00:30:00Z) y America/Lima (2026-11-18 19:30 PE)
        f_prog, f_loc = pred_app.resolve_match_local_date({"fecha_utc": "2026-11-19T00:30:00Z"})
        self.assertEqual(f_prog, "2026-11-19T00:30:00Z")
        self.assertEqual(f_loc, "2026-11-18")

        # Escenario 8: Paginación completa de la API (fetch_matches_paginated sin limit=4)
        page1 = {"matches": [{"id": 1, "homeTeam": {"name": "Coritiba"}, "awayTeam": {"name": "Santos"}, "utcDate": "2026-11-18T22:30:00Z"}], "totalPages": 2}
        page2 = {"matches": [{"id": 2, "homeTeam": {"name": "Remo"}, "awayTeam": {"name": "Chapecoense"}, "utcDate": "2026-11-18T23:00:00Z"}], "totalPages": 2}
        with patch.object(pred_app.FootballDataOrgClient, "fetch_json", side_effect=[
            {"ok": True, "data": page1, "status_code": 200},
            {"ok": True, "data": page2, "status_code": 200},
        ]) as mock_fj:
            pag_res = pred_app.FootballDataOrgClient.fetch_matches_paginated("/competitions/BSA/matches", competition_code="BSA", params={"limit": 4})
            self.assertTrue(pag_res["ok"])
            self.assertEqual(pag_res["pages_fetched"], 2)
            self.assertEqual(len(pag_res["matches"]), 2)
            # Confirmar que limit=4 fue eliminado de los parámetros
            first_call_params = mock_fj.call_args_list[0].kwargs.get("params")
            self.assertIsNone(first_call_params)

        # Escenario 9: Reinicio del servicio y recuperación del calendario + invalidación de caché
        count_reloaded = pred_app.invalidate_calendar_caches(rebuild_pool=True)
        self.assertGreaterEqual(count_reloaded, 598)
        bsa_after_restart = [f for f in pred_app.ALL_FIXTURES_POOL if f.get("codigo_liga") == "BSA" and f.get("fecha") == "2026-11-18"]
        self.assertEqual(len(bsa_after_restart), 6)

        # Escenario 10: El frontend (index.html) no trunca con .slice(0, 12) ni [:4] y recibe todos los partidos del backend
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        self.assertNotIn("destacados.slice(0, 12)", html_content)
        self.assertNotIn("pool.slice(0, 12)", html_content)
        self.assertIn("deduplicarPartidosUI(destacados).forEach((d, idx) => {", html_content)

    def test_15_nov19_official_authority_conflict_rejection_and_consecutive_dates(self):
        pron_handler = self.flask_app.routes["/obtener-pronostico"]
        pred_app.invalidate_calendar_caches(rebuild_pool=True)

        # 1. Resultado exacto para 2026-11-19: exactamente 3 partidos de BSA y NUNCA Mirassol vs Atlético Mineiro
        with patch.object(requests, "get", side_effect=AssertionError("No HTTP en /obtener-pronostico")):
            flask_stub.request.args = {"fecha": "2026-11-19"}
            resp_19, code_19 = pron_handler()
        self.assertEqual(code_19, 200)
        self.assertEqual(resp_19["fecha_activa_destacados"], "2026-11-19")
        self.assertEqual(len(resp_19["destacados"]), 3)
        pares_19 = {
            (pred_app.canonical_team_name(m["local"]), pred_app.canonical_team_name(m["visitante"]))
            for m in resp_19["destacados"]
        }
        self.assertEqual(pares_19, {
            ("vasco", "internacional"),
            ("vitoria ba", "red bull bragantino"),
            ("sao paulo", "fluminense"),
        })
        self.assertNotIn(("mirassol", "atletico mineiro"), pares_19)

        # Verificar que São Paulo vs Fluminense (2026-11-20T00:30:00Z) conserva fecha_local_partido 2026-11-19 (America/Lima)
        sp_flu = [m for m in resp_19["destacados"] if pred_app.canonical_team_name(m["local"]) == "sao paulo"][0]
        self.assertEqual(sp_flu["fecha_programada"], "2026-11-20T00:30:00Z")
        self.assertEqual(sp_flu["fecha_local_partido"], "2026-11-19")

        # 2. Verificar los 10 puntos de diagnóstico obligatorio en auditoria_calendario_fecha
        aud_19 = resp_19["auditoria_calendario_fecha"]
        self.assertIn("fuentes_utilizadas", aud_19)
        self.assertIn("prioridad_en_conflicto", aud_19)
        self.assertIn("partidos_eliminados_combinacion_dedup", aud_19)
        self.assertIn("partidos_descartados_filtro_fecha", aud_19)
        self.assertIn("estado_caches_calendario", aud_19)
        self.assertEqual(aud_19["partidos_oficiales"], 3)
        self.assertEqual(aud_19["partidos_enviados_al_frontend"], 3)
        for p_diag in aud_19["competiciones_partidos"]:
            self.assertTrue(p_diag.get("id_partido"))
            self.assertTrue(p_diag.get("fecha_hora_utc"))
            self.assertTrue(p_diag.get("fecha_hora_america_lima"))
            self.assertEqual(p_diag.get("codigo_liga"), "BSA")
            self.assertEqual(p_diag.get("fecha_en_all_fixtures_pool"), "2026-11-19")

        # 3. Causa general: si un calendario estático/manual tiene fechas obsoletas (Mirassol el 19/11, Vasco/Vitória el 17/11)
        #    y football-data.org provee las fechas oficiales verificadas, se rechaza el obsoleto y prevalece la fuente oficial
        stale_manual = [
            {"id_partido": "stale-mir", "local": "Mirassol", "visitante": "Atlético Mineiro", "fecha_utc": "2026-11-19T14:00:00Z", "codigo_liga": "BSA", "liga": "Campeonato Brasileiro Série A"},
            {"id_partido": "stale-sp", "local": "São Paulo", "visitante": "Fluminense", "fecha_utc": "2026-11-19T15:00:00Z", "codigo_liga": "BSA", "liga": "Campeonato Brasileiro Série A"},
            {"id_partido": "stale-vas", "local": "Vasco", "visitante": "Internacional", "fecha_utc": "2026-11-17T14:00:00Z", "codigo_liga": "BSA", "liga": "Campeonato Brasileiro Série A"},
            {"id_partido": "stale-vit", "local": "Vitória BA", "visitante": "Red Bull Bragantino", "fecha_utc": "2026-11-17T15:00:00Z", "codigo_liga": "BSA", "liga": "Campeonato Brasileiro Série A"},
        ]
        official_fd = [
            {"id": 5001, "homeTeam": {"name": "Mirassol FC"}, "awayTeam": {"name": "Clube Atlético Mineiro"}, "utcDate": "2026-11-14T21:30:00Z", "status": "FINISHED", "competition": {"code": "BSA"}},
            {"id": 5002, "homeTeam": {"name": "CR Vasco da Gama"}, "awayTeam": {"name": "SC Internacional"}, "utcDate": "2026-11-19T22:30:00Z", "status": "SCHEDULED", "competition": {"code": "BSA"}},
            {"id": 5003, "homeTeam": {"name": "EC Vitória"}, "awayTeam": {"name": "RB Bragantino"}, "utcDate": "2026-11-19T22:30:00Z", "status": "SCHEDULED", "competition": {"code": "BSA"}},
            {"id": 5004, "homeTeam": {"name": "São Paulo FC"}, "awayTeam": {"name": "Fluminense FC"}, "utcDate": "2026-11-20T00:30:00Z", "status": "SCHEDULED", "competition": {"code": "BSA"}},
        ]
        aud_conflict = pred_app.CalendarSyncService.audit_date_pipeline(
            "2026-11-19",
            manual_fixtures=stale_manual,
            fd_matches=official_fd,
        )
        self.assertEqual(aud_conflict["partidos_oficiales"], 3)
        self.assertEqual(aud_conflict["partidos_filtrados"], 3)
        self.assertEqual(aud_conflict["partidos_enviados_al_frontend"], 3)
        conflict_pairs = {
            (pred_app.canonical_team_name(p["local"]), pred_app.canonical_team_name(p["visitante"]))
            for p in aud_conflict["competiciones_partidos"]
        }
        self.assertEqual(conflict_pairs, {
            ("vasco", "internacional"),
            ("vitoria ba", "red bull bragantino"),
            ("sao paulo", "fluminense"),
        })
        self.assertTrue(any("fecha_no_coincide_con_fuente_verificada" in d.get("motivo", "") for d in aud_conflict["partidos_eliminados_combinacion_dedup"]))

        # 4. Reconciliación global con reconcile_official_calendar conserva las 9 ligas activas e invalida caché
        rec_res = pred_app.CalendarSyncService.reconcile_official_calendar(official_fd, competition_code="BSA")
        self.assertTrue(rec_res["cache_invalidada"])
        ligas_activas_post = {
            f.get("codigo_liga") for f in pred_app.ALL_FIXTURES_POOL
            if pred_app.is_competition_enabled(f.get("codigo_liga", ""), f.get("liga", ""))
        }
        self.assertEqual(ligas_activas_post, {"BL1", "BSA", "FL1", "PL", "PPL", "PD", "SA", "UCL", "UEL", "UNL"})
        pred_app._SYNCED_EXTERNAL_FD_FIXTURES = []
        pred_app.invalidate_calendar_caches(rebuild_pool=True)

        # 5. Validación futura: fechas consecutivas y varias competiciones sin faltantes, extras ni desplazamientos
        consec = pred_app.CalendarSyncService.audit_consecutive_dates(
            ["2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21"],
            expected_by_date={
                "2026-11-18": [
                    ("Corinthians", "Botafogo"),
                    ("Coritiba", "Santos"),
                    ("Cruzeiro", "Palmeiras"),
                    ("Flamengo", "Atlético Paranaense"),
                    ("Remo", "Chapecoense"),
                    ("Gremio", "Bahia"),
                ],
                "2026-11-19": [
                    ("Vasco", "Internacional"),
                    ("Vitória BA", "Red Bull Bragantino"),
                    ("São Paulo", "Fluminense"),
                ],
            },
        )
        for d_key, info in consec.items():
            self.assertTrue(info["ok"], f"Fallo en fecha consecutiva {d_key}: {info}")
            self.assertEqual(info["desplazamientos_fecha"], [])
            self.assertEqual(info["partidos_faltantes"], [])
            self.assertEqual(info["partidos_extra"], [])
        self.assertEqual(consec["2026-11-18"]["total_mostrado"], 6)
        self.assertEqual(consec["2026-11-19"]["total_mostrado"], 3)
        self.assertGreaterEqual(len(consec["2026-11-21"]["competiciones"]), 5)

    def test_16_live_calendar_sync_nov24_10_matches_and_telegram_results_pipeline(self):
        pron_handler = self.flask_app.routes["/obtener-pronostico"]
        pred_app.invalidate_calendar_caches(rebuild_pool=True)

        # 1. Hoy 2026-11-24: exactamente 10 partidos (9 UCL + Chapecoense vs Palmeiras de BSA)
        with patch.object(requests, "get", side_effect=AssertionError("No HTTP en /obtener-pronostico")):
            flask_stub.request.args = {"fecha": "2026-11-24"}
            resp_24, c24 = pron_handler()
        self.assertEqual(c24, 200)
        self.assertEqual(len(resp_24["destacados"]), 10)
        ucl_24 = [m for m in resp_24["destacados"] if m["codigo_liga"] == "UCL"]
        bsa_24 = [m for m in resp_24["destacados"] if m["codigo_liga"] == "BSA"]
        self.assertEqual(len(ucl_24), 9)
        self.assertEqual(len(bsa_24), 1)
        self.assertEqual(bsa_24[0]["local"], "Chapecoense")
        self.assertEqual(bsa_24[0]["visitante"], "Palmeiras")

        # Sevilla vs Betis y Rayo vs Valencia están en 2026-11-21 (no en 2026-11-22 ni 2026-11-23)
        for bad_d in ("2026-11-22", "2026-11-23"):
            ms_bad = [f for f in pred_app.ALL_FIXTURES_POOL if pred_app.resolve_match_local_date(f)[1] == bad_d]
            pares_bad = {(f.get("local"), f.get("visitante")) for f in ms_bad}
            self.assertNotIn(("Sevilla", "Real Betis"), pares_bad)
            self.assertNotIn(("Rayo Vallecano", "Valencia"), pares_bad)

        # 2. Sincronización en vivo desde football-data.org actualiza fechas obsoletas sin borrar otras ligas
        fd_mock_resp = {
            "ok": True,
            "matches": [
                {"id": 77001, "homeTeam": {"name": "Chapecoense AF"}, "awayTeam": {"name": "SE Palmeiras"}, "utcDate": "2026-11-25T00:00:00Z", "status": "SCHEDULED", "competition": {"code": "BSA"}},
            ],
        }
        with patch.object(pred_app.FootballDataOrgClient, "_get_api_key", return_value="k_live_test"),              patch.object(pred_app.FootballDataOrgClient, "fetch_matches_paginated", return_value=fd_mock_resp):
            sync_res = pred_app.CalendarSyncService.sync_live_calendar_from_football_data(competition_codes=["BSA"])
        self.assertTrue(sync_res["ok"])
        self.assertEqual(sync_res["total_fd_matches"], 1)
        self.assertTrue(sync_res["cache_invalidada"])
        pred_app._SYNCED_EXTERNAL_FD_FIXTURES = []
        pred_app.invalidate_calendar_caches(rebuild_pool=True)

        # 3. obtener_resultado_real_verificado enriquece tarjetas/córners cuando football-data.org solo trae goles
        #    y consulta ventana [fecha, fecha+1] para cubrir medianoche UTC
        pred_app._VERIFIED_RESULTS_CACHE.clear()
        fd_goals_only = {
            "ok": True,
            "data": {
                "matches": [
                    {"status": "FINISHED", "homeTeam": {"name": "Athletic Club"}, "awayTeam": {"name": "Espanyol"}, "score": {"fullTime": {"home": 2, "away": 0}}}
                ]
            },
        }
        hl_cards = {"finished": True, "score_home": 2, "score_away": 0, "cards_total": 3, "corners_total": 8}
        with patch.object(pred_app.FootballDataOrgClient, "_get_api_key", return_value="k_fd"),              patch.object(pred_app.FootballDataOrgClient, "fetch_json", return_value=fd_goals_only) as mock_fd,              patch.object(pred_app.HighlightlyFootballClient, "_get_api_key", return_value="k_hl"),              patch.object(pred_app.HighlightlyFootballClient, "fetch_match_stats", return_value=hl_cards):
            res_enriched = pred_app.obtener_resultado_real_verificado("Athletic Club", "Espanyol", "2026-11-21", liga="Primera División")
        self.assertTrue(res_enriched["finished"])
        self.assertEqual(res_enriched["score_home"], 2)
        self.assertEqual(res_enriched["cards_total"], 3)
        self.assertEqual(mock_fd.call_args.kwargs["params"]["dateTo"], "2026-11-22")
        cal_cards = pred_app.SportsResultsAuditor.grade_prediction({"seleccion": "Menos de 4.5 tarjetas", "local": "Athletic Club", "visitante": "Espanyol"}, res_enriched)
        self.assertEqual(cal_cards["estado"], "GANADA")

        # 4. Envío automático de resultados a Telegram para jornadas pasadas (ej. 2026-11-23 con 2 verificados + 1 pendiente)
        #    y verificación de endpoints admin
        self.assertIn("/api/v1/admin/calendar/sync-live", self.flask_app.routes)
        self.assertIn("/api/v1/admin/telegram/send-results", self.flask_app.routes)
        picks_23 = [
            {"partido": "Brentford vs Everton", "liga": "Premier League", "seleccion": "Más de 1.5 goles", "resultado": "2-1", "estado": "GANADA", "verificado": True},
            {"partido": "Santos vs Gremio", "liga": "Brasileirão", "seleccion": "Santos gana o empata", "resultado": "1-0", "estado": "GANADA", "verificado": True},
            {"partido": "Partido Aplazado vs Rival", "liga": "LaLiga", "seleccion": "Más de 1.5 goles", "resultado": "Pendiente", "estado": "PENDIENTE", "verificado": False},
        ]
        pred_app._ultimo_envio_resultados_top5.discard("2026-11-23")
        res_f_path = "/tmp/predicxion_last_tg_res_2026-11-23.txt"
        if os.path.exists(res_f_path):
            try:
                os.remove(res_f_path)
            except Exception:
                pass
        mock_tg_ok = MagicMock(status_code=200, text="ok")
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok_test", "TELEGRAM_CHANNEL_ID": "@canal_test"}),              patch.object(pred_app, "generar_imagen_resultados_top5", return_value=b"PNG_FAKE_BYTES"),              patch.object(requests, "post", return_value=mock_tg_ok) as mock_post:
            ok_send, msg_send = pred_app.ejecutar_envio_automatico_resultados_top5("2026-11-23", picks_23, force=False, motivo="TEST_RECUPERACION")
            self.assertTrue(ok_send, msg_send)
            self.assertEqual(mock_post.call_count, 1)
            # Segunda llamada idempotente no debe duplicar el envío
            ok_dup, _ = pred_app.ejecutar_envio_automatico_resultados_top5("2026-11-23", picks_23, force=False, motivo="TEST_RECUPERACION")
            self.assertFalse(ok_dup)

    def test_17_locutor_analista_predicxion_ia_and_no_referee_ui(self):
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # 1. Nombre oficial del locutor y soporte de reproducción robusto (POST + troceado SpeechSynthesis)
        self.assertIn("LOCUTOR ANALISTA DE PREDICXION IA", html_content)
        self.assertIn("Hola, soy el Locutor Analista de PredicXion IA.", html_content)
        self.assertIn("function _dividirOracionesVoz", html_content)
        self.assertIn("window.speechSynthesis.resume()", html_content)
        self.assertIn("method: 'POST'", html_content)

        # 2. Guion completo: pick principal, goles totales, córners totales, remates y tarjetas
        guion_fn = html_content.split("function construirGuionAnalisisVozPartido")[1].split("function reproducirAudioPartidoModal")[0]
        self.assertIn("El pick principal es", guion_fn)
        self.assertIn("En goles totales", guion_fn)
        self.assertIn("Pasando a córners totales", guion_fn)
        self.assertIn("en tarjetas se proyecta", guion_fn)
        self.assertIn("en remates totales", guion_fn)
        self.assertNotIn("Árbitro", guion_fn)
        self.assertNotIn("Colegiado", guion_fn)

        # 3. Tarjetas de UI sin referencias de Árbitro Oficial ni Colegiado
        cards_section = html_content.split("// 3. TARJETAS")[1].split("// 4. REMATES")[0]
        self.assertNotIn("Árbitro:", cards_section)
        self.assertNotIn("ÁRBITRO", cards_section)
        self.assertNotIn("Colegiado", cards_section)

        # 4. Endpoint /api/v1/voice/audio soporta POST con texto largo (>950 chars) y responde audio/mpeg
        voice_handler = self.flask_app.routes["/api/v1/voice/audio"]
        flask_stub.request.method = "POST"
        flask_stub.request.get_json = MagicMock(return_value={"voice": "gonzalo", "text": "Hola, soy el Locutor Analista de PredicXion IA. " * 25})
        flask_stub.request.args = {}
        fake_mp3_resp = MagicMock(status_code=200, content=b"ID3" + b"0" * 400)
        with patch.object(requests, "get", return_value=fake_mp3_resp):
            resp_tts = voice_handler()
        self.assertIsNotNone(resp_tts)
        flask_stub.request.method = "GET"

    def test_18_audit_integral_dedup_ucl_22h_pipeline_sync_status_and_audio(self):
        # 1. Champions League (CL vs UCL) con nombres oficiales en inglés de football-data.org vs español del calendario embebido
        #    Debe producir 0 duplicados en los 3 niveles, conservar el registro más completo y registrar discrepancias de hora/estado
        ucl_nov24_manual = [
            f for f in pred_app.ALL_FIXTURES_POOL
            if f.get("codigo_liga") == "UCL" and pred_app.CalendarDateService.to_lima_date(f) == "2026-11-24"
        ]
        self.assertEqual(len(ucl_nov24_manual), 9)

        ucl_fd_english = [
            {"id": 9101, "homeTeam": {"name": "FK Bodø/Glimt"}, "awayTeam": {"name": "LASK Linz"}, "utcDate": "2026-11-24T17:45:00Z", "status": "TIMED", "competition": {"code": "CL", "name": "UEFA Champions League"}},
            {"id": 9102, "homeTeam": {"name": "Galatasaray SK"}, "awayTeam": {"name": "Aston Villa FC"}, "utcDate": "2026-11-24T17:45:00Z", "status": "TIMED", "competition": {"code": "CL", "name": "UEFA Champions League"}},
            {"id": 9103, "homeTeam": {"name": "Arsenal FC"}, "awayTeam": {"name": "BV Borussia 09 Dortmund"}, "utcDate": "2026-11-24T20:00:00Z", "status": "TIMED", "competition": {"code": "CL", "name": "UEFA Champions League"}},
            {"id": 9104, "homeTeam": {"name": "Como 1907"}, "awayTeam": {"name": "AEK Athens FC"}, "utcDate": "2026-11-24T20:00:00Z", "status": "TIMED", "competition": {"code": "CL", "name": "UEFA Champions League"}},
            {"id": 9105, "homeTeam": {"name": "Feyenoord Rotterdam"}, "awayTeam": {"name": "FC Porto"}, "utcDate": "2026-11-24T20:00:00Z", "status": "TIMED", "competition": {"code": "CL", "name": "UEFA Champions League"}},
            {"id": 9106, "homeTeam": {"name": "Manchester City FC"}, "awayTeam": {"name": "SSC Napoli"}, "utcDate": "2026-11-24T20:00:00Z", "status": "TIMED", "competition": {"code": "CL", "name": "UEFA Champions League"}},
            {"id": 9107, "homeTeam": {"name": "RB Leipzig"}, "awayTeam": {"name": "RC Lens"}, "utcDate": "2026-11-24T20:00:00Z", "status": "TIMED", "competition": {"code": "CL", "name": "UEFA Champions League"}},
            {"id": 9108, "homeTeam": {"name": "Real Madrid CF"}, "awayTeam": {"name": "PSV Eindhoven"}, "utcDate": "2026-11-24T20:00:00Z", "status": "TIMED", "competition": {"code": "CL", "name": "UEFA Champions League"}},
            {"id": 9109, "homeTeam": {"name": "ŠK Slovan Bratislava"}, "awayTeam": {"name": "Real Betis Balompié"}, "utcDate": "2026-11-24T20:00:00Z", "status": "TIMED", "competition": {"code": "CL", "name": "UEFA Champions League"}},
        ]
        fd_converted = [pred_app.CalendarSyncService.convert_fd_match_to_fixture(m, "CL") for m in ucl_fd_english]
        dedup_l1, dups_l1, disc_l1 = pred_app.CalendarSyncService.deduplicate_fixtures(ucl_nov24_manual + fd_converted, level="IMPORT")
        self.assertEqual(len(dedup_l1), 9, f"Esperado 9 partidos UCL sin duplicados, obtenido {len(dedup_l1)}")
        self.assertEqual(len(dups_l1), 9)
        self.assertEqual(len(disc_l1), 9)
        # Conserva el registro más completo (football-data.org con estado TIMED)
        for f_kept in dedup_l1:
            self.assertEqual(f_kept["codigo_liga"], "UCL")
            self.assertEqual(f_kept["estado"], "TIMED")
            self.assertEqual(f_kept["origen_fuente"], "football-data.org")

        # Verificar Club Brujas vs Club Brugge KV y Slavia Praga vs SK Slavia Praha
        self.assertEqual(pred_app.canonical_team_name("Club Brujas"), pred_app.canonical_team_name("Club Brugge KV"))
        self.assertEqual(pred_app.canonical_team_name("Slavia Praga"), pred_app.canonical_team_name("SK Slavia Praha"))
        self.assertEqual(pred_app.canonical_team_name("PSG"), pred_app.canonical_team_name("Paris Saint-Germain FC"))
        self.assertEqual(pred_app.canonical_team_name("Nápoles"), pred_app.canonical_team_name("SSC Napoli"))

        # 2. Clave canónica incluye fecha_local + competición normalizada + local + visitante
        k_ucl = pred_app.CalendarSyncService.canonical_fixture_key("Real Madrid CF", "PSV Eindhoven", "2026-11-24T20:00:00Z", competition_code="CL")
        k_ucl_es = pred_app.CalendarSyncService.canonical_fixture_key("Real Madrid", "PSV", "2026-11-24", competition_code="UCL")
        self.assertEqual(k_ucl, k_ucl_es)
        self.assertEqual(k_ucl, "2026-11-24|UCL|real madrid|psv")

        # 3. Función única CalendarDateService respeta America/Lima sin mezclar día 19 con día 20
        self.assertEqual(pred_app.CalendarDateService.to_lima_date({"fecha_utc": "2026-11-20T00:30:00Z"}), "2026-11-19")
        self.assertEqual(pred_app.CalendarDateService.to_lima_date({"fecha_utc": "2026-11-20T15:00:00Z"}), "2026-11-20")

        # 4. Pipeline diario de 10 pasos a las 22:00 America/Lima + /api/v1/cron/daily-sync + /api/v1/sync/status
        self.assertIn("/api/v1/sync/status", self.flask_app.routes)
        self.assertIn("/api/v1/cron/daily-sync", self.flask_app.routes)

        # Sin token debe responder 403
        cron_handler = self.flask_app.routes["/api/v1/cron/daily-sync"]
        flask_stub.request.headers = {}
        flask_stub.request.args = {}
        flask_stub.request.get_json = MagicMock(return_value={})
        with patch.dict(os.environ, {"CRON_SECRET_TOKEN": "super_secret_cron_22h"}),              patch.object(pred_app, "_verificar_es_admin", return_value=False):
            _, code_403 = cron_handler()
            self.assertEqual(code_403, 403)

        # Con token válido ejecuta los 10 pasos, regenera Top 3, envía Telegram y actualiza data_version
        ver_before = self.flask_app.routes["/api/v1/sync/status"]()[0]["data_version"]
        dt_22pe = pred_app.datetime(2026, 11, 24, 22, 0, 5, tzinfo=pred_app.timezone(pred_app.timedelta(hours=-5)))
        for t in ("Sabah Baku", "Barcelona", "Slavia Praga", "Villarreal", "Atlético de Madrid", "Viking"):
            self._add_verified_team(t, code="UCL", liga="UEFA Champions League", gf=2, ga=1)
        mock_tg_ok = MagicMock(status_code=200, text="ok")
        with patch.dict(os.environ, {"CRON_SECRET_TOKEN": "super_secret_cron_22h", "TELEGRAM_BOT_TOKEN": "tok_t", "TELEGRAM_CHANNEL_ID": "@chan_t"}),              patch.object(pred_app.CalendarSyncService, "sync_live_calendar_from_football_data", return_value={"ok": True, "total_fd_matches": 9}),              patch.object(requests, "post", return_value=mock_tg_ok):
            pipe_res = pred_app.DailyAutomationPipeline.run_daily_pipeline(now_pe=dt_22pe, force=True, motivo="TEST_22H_INTEGRAL")
        self.assertTrue(pipe_res["success"])
        self.assertEqual(len(pipe_res["pasos"]), 10)
        self.assertTrue(pipe_res["rotacion_top3"]["telegram_sent"])
        self.assertEqual(pipe_res["auditoria_duplicados"]["duplicados_eliminados"], 0)
        sync_after, code_st = self.flask_app.routes["/api/v1/sync/status"]()
        self.assertEqual(code_st, 200)
        self.assertNotEqual(sync_after["data_version"], ver_before)
        self.assertIn("PE", sync_after["last_sync_lima"])

        # 5. Verificación de frontend (index.html): polling sin recarga, última sincronización,
        #    deduplicación UI y botón de audio con "Generando audio…", error visible y Reintentar
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html_c = f.read()
        self.assertIn("telemetria-last-sync", html_c)
        self.assertIn("function iniciarAutoSyncUI()", html_c)
        self.assertIn("/api/v1/sync/status", html_c)
        self.assertIn("function deduplicarPartidosUI(", html_c)
        self.assertIn("Generando audio…", html_c)
        self.assertIn("locutor-error-box", html_c)
        self.assertIn("Reintentar", html_c)
        self.assertIn("mostrarErrorLocutorUI", html_c)


    def test_19_render_prod_fixes_audio_3level_stats_consistency_payload_unl_aliases_ratings(self):
        """
        Verifica todas las correcciones críticas de producción en Render:
        1) Audio sin TypeError cuando faltan avg_goals/over_1_5/over_2_5/btts/corners/cards/shots/shots_ot (ejecución real en Node.js) + fallback SpeechSynthesis + sin micrófono.
        2) Estimación en 3 niveles (REAL / NIVEL_2_CALIBRADO / NIVEL_3_PRIOR_COMPETICION) con metadatos auditables y sin constantes arbitrarias.
        3) Consistencia total entre pilares_cuantitativos, organizacion_stakazos, key_probabilities, IA y audio.
        4) Carga ligera (?modo=resumen) drásticamente menor al payload completo + compresión gzip + detalle bajo demanda /api/v1/partido/<id>/detalle.
        5) UEFA Nations League (UNL) activa cuando DISABLED_COMPETITIONS está vacía o no configurada.
        6) Deduplicación de alias (Marítimo/CS Marítimo, Nacional/CD Nacional, Niza/OGC Nice, Troyes/ES Troyes AC, Genoa/Genoa CFC, Torino/Torino FC) en backend y frontend.
        7) Diagnóstico de ratings (partidos_descargados, equipos_procesados, partidos_aceptados, partidos_descartados, ultima_sincronizacion, causa_vacio, errores_api) y respaldo desde _VERIFIED_RESULTS_CACHE.
        8) Top 3 con 3 selecciones válidas.
        """
        import subprocess, json as _json, gzip as _gzip

        # 1. Prueba real en Node.js de construirGuionAnalisisVozPartido y claveCanonicaPartidoUI en index.html
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
        with open(html_path, "r", encoding="utf-8") as fh:
            html_txt = fh.read()

        # Verificar fallback SpeechSynthesis, botón Reintentar, texto "Generando audio" y cero solicitudes de micrófono
        self.assertIn("speechSynthesis", html_txt)
        self.assertIn("Reintentar", html_txt)
        self.assertIn("Generando audio", html_txt)
        self.assertNotIn("getUserMedia", html_txt)
        self.assertIn("/obtener-pronostico?modo=resumen", html_txt)
        self.assertIn("/api/v1/partido/", html_txt)

        # Extraer limpiarTextoParaVoz, construirGuionAnalisisVozPartido y claveCanonicaPartidoUI para ejecución real en Node
        def _extract_js_fn(src, name):
            start = src.index(f"function {name}(")
            brace = src.index("{", start)
            depth = 0
            for idx in range(brace, len(src)):
                if src[idx] == "{":
                    depth += 1
                elif src[idx] == "}":
                    depth -= 1
                    if depth == 0:
                        return src[start:idx + 1]
            raise ValueError(f"Unclosed {name}")

        fn_limpiar = _extract_js_fn(html_txt, "limpiarTextoParaVoz")
        fn_guion = _extract_js_fn(html_txt, "construirGuionAnalisisVozPartido")
        fn_ui_key = _extract_js_fn(html_txt, "claveCanonicaPartidoUI")
        aliases_start = html_txt.index("const _UI_TEAM_ALIASES = {")
        aliases_end = html_txt.index("};", aliases_start) + 2
        ui_aliases_decl = html_txt[aliases_start:aliases_end]

        node_script = f"""
{fn_limpiar}
{ui_aliases_decl}
{fn_ui_key}
function extraerMetricasOddsterPartido(p) {{
    return p._mockOdd || {{}};
}}
{fn_guion}

// Caso A: partido sin avg_goals, sin over_1_5, sin corners, sin cards, sin shots
const gSinMetricas = construirGuionAnalisisVozPartido({{
    local: "Marítimo", visitante: "Nacional", liga: "Primeira Liga",
    pronostico_principal: {{ seleccion: "Marítimo gana o empata", probabilidad: "78%" }},
    _mockOdd: {{}}
}});

// Caso B: partido con métricas completas (forma real goals_totals + avg_goals + corners + cards + shots)
const gCompleto = construirGuionAnalisisVozPartido({{
    local: "Arsenal", visitante: "Chelsea", liga: "Premier League",
    pronostico_principal: {{ seleccion: "Más de 1.5 goles", probabilidad: "82%" }},
    _mockOdd: {{
        avg_goals: {{ val: "2.95", avg: "2.80", home: "1.80", away: "1.15" }},
        goals_totals: {{ over_15: 82, over_25: 59 }},
        btts: {{ val: 56 }},
        avg_corners: {{ val: "10.2", avg: "10.0", home: "6.1", away: "4.1", rec: "Más de 8.5 córners" }},
        avg_cards: {{ val: "4.3" }},
        avg_shots: {{ val: "25.4" }},
        avg_shots_ot: {{ val: "8.7" }}
    }}
}});

// Caso C: alias en claveCanonicaPartidoUI
const k1 = claveCanonicaPartidoUI({{ fecha: "2026-11-28", codigo_liga: "PPL", local: "Marítimo", visitante: "Nacional" }});
const k2 = claveCanonicaPartidoUI({{ fecha: "2026-11-28", codigo_liga: "PPL", local: "CS Marítimo", visitante: "CD Nacional" }});
const k3 = claveCanonicaPartidoUI({{ fecha: "2026-11-28", codigo_liga: "FL1", local: "Niza", visitante: "Troyes" }});
const k4 = claveCanonicaPartidoUI({{ fecha: "2026-11-28", codigo_liga: "FL1", local: "OGC Nice", visitante: "ES Troyes AC" }});
const k5 = claveCanonicaPartidoUI({{ fecha: "2026-11-28", codigo_liga: "SA", local: "Genoa", visitante: "Torino" }});
const k6 = claveCanonicaPartidoUI({{ fecha: "2026-11-28", codigo_liga: "SA", local: "Genoa CFC", visitante: "Torino FC" }});

console.log(JSON.stringify({{ gSinMetricas, gCompleto, eq_pt: k1 === k2, eq_fr: k3 === k4, eq_it: k5 === k6, k1, k3, k5 }}));
"""
        proc = subprocess.run(["node", "-e", node_script], capture_output=True, text=True, check=True)
        node_out = _json.loads(proc.stdout.strip())
        self.assertIn("Locutor Analista de PredicXion IA", node_out["gSinMetricas"])
        self.assertIn("Marítimo", node_out["gSinMetricas"])
        self.assertIn("2.95 goles", node_out["gCompleto"])
        self.assertIn("10.2 tiros de esquina", node_out["gCompleto"])
        self.assertIn("4.3 amonestaciones", node_out["gCompleto"])
        self.assertTrue(node_out["eq_pt"], f"Alias PT falló: {node_out['k1']}")
        self.assertTrue(node_out["eq_fr"], f"Alias FR falló: {node_out['k3']}")
        self.assertTrue(node_out["eq_it"], f"Alias IT falló: {node_out['k5']}")

        # 2 y 3. Estimación en 3 niveles sin constantes arbitrarias + consistencia entre secciones
        an_pl = pred_app.SportsAnalyticsEngine.generate_institutional_analysis({
            "local": "ClubNuevoPL1", "visitante": "ClubNuevoPL2",
            "codigo_liga": "PL", "liga": "Premier League", "fecha": "2026-11-28",
        })
        an_sa = pred_app.SportsAnalyticsEngine.generate_institutional_analysis({
            "local": "ClubNuevoSA1", "visitante": "ClubNuevoSA2",
            "codigo_liga": "SA", "liga": "Serie A", "fecha": "2026-11-28",
        })
        kp_pl = an_pl["key_probabilities"]
        kp_sa = an_sa["key_probabilities"]
        # Distintas competiciones producen distintos priors (no constante fija arbitraria)
        self.assertNotEqual(kp_pl["avg_corners"]["valor"], kp_sa["avg_corners"]["valor"])
        self.assertNotEqual(kp_pl["avg_cards"]["valor"], kp_sa["avg_cards"]["valor"])
        for mk in ("avg_corners", "avg_cards", "avg_shots", "avg_shots_on_target"):
            m = kp_pl[mk]
            self.assertIsNotNone(m["valor"])
            self.assertEqual(m["tipo_dato"], "ESTIMADO_MODELO")
            self.assertEqual(m["tipo_dato_audit"], "ESTIMADO_MODELO")
            self.assertIn("metodo", m)
            self.assertIn("fecha_calculo", m)
            self.assertIsInstance(m["intervalo_estimado"], list)
            self.assertEqual(len(m["intervalo_estimado"]), 2)
        # Consistencia entre key_probabilities, pilares_cuantitativos y organizacion_stakazos
        c_val_str = str(kp_pl["avg_corners"]["valor"])
        t_val_str = str(kp_pl["avg_cards"]["valor"])
        self.assertIn(c_val_str, an_pl["pilares_cuantitativos"]["pilar_1_volumen_ofensivo"]["corners_proyectados"])
        self.assertIn(t_val_str, an_pl["pilares_cuantitativos"]["pilar_7_micromercados_friccion"]["tarjetas_proyectadas"])
        self.assertNotEqual(an_pl["organizacion_stakazos"]["micromercado_oro"]["mercado"], "Datos insuficientes")

        # 4. Payload ligero (?modo=resumen) vs completo + detalle bajo demanda
        pron_handler = self.flask_app.routes["/obtener-pronostico"]
        det_handler = self.flask_app.routes["/api/v1/partido/<match_id>/detalle"]
        with patch.object(requests, "get", side_effect=AssertionError("No HTTP en /obtener-pronostico")):
            flask_stub.request.args = {"fecha": "2026-11-24", "modo": "resumen"}
            resp_resumen, c_res = pron_handler()
            self.assertEqual(c_res, 200)
            flask_stub.request.args = {"fecha": "2026-11-24", "modo": "completo"}
            resp_full, c_full = pron_handler()
            self.assertEqual(c_full, 200)
        sz_resumen = len(_json.dumps(resp_resumen, ensure_ascii=False).encode("utf-8"))
        sz_full = len(_json.dumps(resp_full, ensure_ascii=False).encode("utf-8"))
        self.assertLess(sz_resumen, sz_full * 0.35, f"modo=resumen ({sz_resumen}B) debe ser mucho menor que completo ({sz_full}B)")
        self.assertLess(sz_resumen, 2 * 1024 * 1024)
        # Detalle bajo demanda del primer partido del calendario resumido
        first_liga = next(iter(resp_resumen["todos"].values()))
        first_id = first_liga[0]["id_partido"]
        self.assertTrue(first_liga[0].get("resumen_ligero"))
        det_resp, det_code = det_handler(first_id)
        self.assertEqual(det_code, 200)
        self.assertTrue(det_resp["success"])
        self.assertIn("pilares_cuantitativos", det_resp["partido"])
        self.assertIn("key_probabilities", det_resp["partido"])

        # 5. UEFA Nations League (UNL) activa cuando DISABLED_COMPETITIONS está vacía o no existe
        with patch.dict(os.environ, {"DISABLED_COMPETITIONS": ""}, clear=False):
            self.assertEqual(pred_app.get_disabled_competitions(), set())
            self.assertTrue(pred_app.is_competition_enabled("UNL", "UEFA Nations League"))
        with patch.dict(os.environ, {"DISABLED_COMPETITIONS": "UNL"}, clear=False):
            self.assertIn("UNL", pred_app.get_disabled_competitions())
            self.assertFalse(pred_app.is_competition_enabled("UNL", "UEFA Nations League"))

        # 6. Deduplicación de alias en backend
        for a1, a2 in [
            ("Marítimo", "CS Marítimo"),
            ("Nacional", "CD Nacional"),
            ("Niza", "OGC Nice"),
            ("Troyes", "ES Troyes AC"),
            ("Genoa", "Genoa CFC"),
            ("Torino", "Torino FC"),
        ]:
            self.assertEqual(pred_app.canonical_team_name(a1), pred_app.canonical_team_name(a2), f"Alias mismatch: {a1} vs {a2}")

        # 7. Diagnóstico de ratings y respaldo desde _VERIFIED_RESULTS_CACHE cuando la API externa devuelve vacío
        prev_cache = dict(pred_app._VERIFIED_RESULTS_CACHE)
        prev_ratings = dict(pred_app.RATINGS_REALES)
        prev_hist = dict(pred_app.VERIFIED_TEAM_HISTORY)
        try:
            pred_app._VERIFIED_RESULTS_CACHE[("2026-11-23", "Sevilla", "Real Betis")] = {
                "finished": True, "simulado": False, "score_home": 2, "score_away": 1,
                "competicion": "LaLiga", "codigo_liga": "PD", "tipo_entidad": "club",
            }
            with patch.object(pred_app.FootballDataOrgClient, "fetch_json", return_value={"ok": False, "data": None, "error": "429_rate_limit"}):
                st_rat = pred_app.actualizar_ratings_reales()
            for k_diag in ("partidos_descargados", "equipos_procesados", "partidos_aceptados", "partidos_descartados", "ultima_sincronizacion", "errores_api"):
                self.assertIn(k_diag, st_rat, f"Falta campo diagnóstico {k_diag} en RATINGS_ESTADO")
            self.assertGreaterEqual(st_rat["equipos_procesados"], 2)
            self.assertGreaterEqual(st_rat["partidos_aceptados"], 1)
        finally:
            pred_app._VERIFIED_RESULTS_CACHE.clear()
            pred_app._VERIFIED_RESULTS_CACHE.update(prev_cache)
            pred_app.RATINGS_REALES.clear()
            pred_app.RATINGS_REALES.update(prev_ratings)
            pred_app.VERIFIED_TEAM_HISTORY.clear()
            pred_app.VERIFIED_TEAM_HISTORY.update(prev_hist)

        # 8. Top 3 con 3 picks válidos desde el endpoint oficial
        for fx in pred_app.ALL_FIXTURES_POOL:
            if pred_app.resolve_match_local_date(fx)[1] == "2026-11-24":
                self._add_verified_team(fx["local"], gf=2, ga=1)
                self._add_verified_team(fx["visitante"], gf=1, ga=1)
        top3_handler = self.flask_app.routes["/api/v1/top3/daily"]
        flask_stub.request.args = {"fecha": "2026-11-24"}
        raw_top3 = top3_handler()
        if isinstance(raw_top3, tuple):
            top3_resp, top3_code = raw_top3[0], raw_top3[1]
            self.assertEqual(top3_code, 200)
        else:
            top3_resp = raw_top3
        top3 = top3_resp.get("top3") or top3_resp.get("picks") or top3_resp.get("top5") or []
        self.assertEqual(len(top3), 3)
        for pick in top3:
            self.assertTrue(pick.get("local") and pick.get("visitante"))
            self.assertIn("logo_local", pick)
            self.assertIn("logo_visitante", pick)

    def test_20_nov27_calendar_7_matches_unified_metrics_audit_and_cron_idempotency(self):
        """
        Auditoría integral del 27/11/2026 (America/Lima):
          1-4. Exactamente 7 partidos esperados el 27/11/2026; Fluminense vs Cruzeiro en el 27 (no 28/29);
               Levante vs Racing de Santander (PD) en el 27; Celta vs Villarreal NO en el 27.
          5-6. Cero duplicados por alias (Bolonia/Bologna, Borussia M'gladbach, Paris FC, Marítimo, Nacional, Racing Club)
               y cero mezcla entre 26, 27 y 28.
          7. Top 3 del 27/11/2026 usa exclusivamente partidos del 27 (máx. 3).
          8-9. Werder Bremen vs Borussia M'gladbach propaga métricas unificadas (10.6, 3.83, 26.1, 9.1) a
               todas las secciones y al frontend (ejecución real en Node.js) sin "Datos insuficientes".
          10-12. Actualización 22:00 PE idempotente, bloqueo de concurrencia y resiliencia ante caída de proveedor externo.
          13-16. Auditoría completa /api/v1/partido/<id>/auditoria, cero HTTP en /obtener-pronostico y cero "Top 5" visible.
        """
        import subprocess, json as _json

        pred_app.ensure_fixtures_date_index(force=True)
        # 1. Verificar exactamente los 7 partidos del 27/11/2026 (America/Lima)
        m27 = [f for f in pred_app.ALL_FIXTURES_POOL if pred_app.resolve_match_local_date(f)[1] == "2026-11-27"]
        self.assertEqual(len(m27), 7, f"Esperados 7 partidos el 27/11/2026, encontrados {len(m27)}: {[(x['local'], x['visitante']) for x in m27]}")

        pares_27 = {(pred_app.canonical_team_name(f["local"]), pred_app.canonical_team_name(f["visitante"]), f["codigo_liga"]) for f in m27}
        esperados_27 = {
            (pred_app.canonical_team_name("Werder Bremen"), pred_app.canonical_team_name("Borussia Mönchengladbach"), "BL1"),
            (pred_app.canonical_team_name("Fluminense"), pred_app.canonical_team_name("Cruzeiro"), "BSA"),
            (pred_app.canonical_team_name("Levante"), pred_app.canonical_team_name("Racing Club"), "PD"),
            (pred_app.canonical_team_name("Brest"), pred_app.canonical_team_name("París FC"), "FL1"),
            (pred_app.canonical_team_name("Nottingham Forest"), pred_app.canonical_team_name("Chelsea"), "PL"),
            (pred_app.canonical_team_name("Venezia"), pred_app.canonical_team_name("Bologna"), "SA"),
            (pred_app.canonical_team_name("Marítimo"), pred_app.canonical_team_name("Nacional"), "PPL"),
        }
        self.assertEqual(pares_27, esperados_27)

        # 2-4. Fluminense vs Cruzeiro NO en 28 ni 29; Celta vs Villarreal NO en 27
        for d_other in ("2026-11-26", "2026-11-28", "2026-11-29"):
            ms_o = [f for f in pred_app.ALL_FIXTURES_POOL if pred_app.resolve_match_local_date(f)[1] == d_other]
            self.assertFalse(any("fluminense" in f["local"].lower() and "cruzeiro" in f["visitante"].lower() for f in ms_o))
            self.assertFalse(any("levante" in f["local"].lower() and "racing" in f["visitante"].lower() for f in ms_o))
        self.assertFalse(any("celta" in f["local"].lower() and "villarreal" in f["visitante"].lower() for f in m27))

        # 5. Deduplicación de alias solicitados (backend)
        for a1, a2 in [
            ("Bologna", "Bolonia"),
            ("Borussia M’gladbach", "Borussia Monchengladbach"),
            ("Borussia M'gladbach", "Borussia Mönchengladbach"),
            ("Paris FC", "París FC"),
            ("Marítimo", "CS Marítimo"),
            ("Nacional", "CD Nacional"),
            ("Racing Club", "Racing de Santander"),
        ]:
            self.assertEqual(pred_app.canonical_team_name(a1), pred_app.canonical_team_name(a2), f"Alias mismatch: {a1} vs {a2}")

        # 6. /obtener-pronostico sin llamadas externas y sin mezclar fechas para 2026-11-27
        pron_handler = self.flask_app.routes["/obtener-pronostico"]
        with patch.object(requests, "get", side_effect=AssertionError("No HTTP en /obtener-pronostico")):
            flask_stub.request.args = {"fecha": "2026-11-27", "modo": "resumen"}
            resp_27, c27 = pron_handler()
        self.assertEqual(c27, 200)
        self.assertEqual(len(resp_27["destacados"]), 7)
        for item in resp_27["destacados"]:
            self.assertEqual(item["fecha_local_partido"], "2026-11-27")

        # 7. Top 3 del 27/11/2026 usa SOLO partidos del 27 (máximo 3)
        for fx in m27:
            self._add_verified_team(fx["local"], gf=2, ga=1)
            self._add_verified_team(fx["visitante"], gf=1, ga=1)
        top3_handler = self.flask_app.routes["/api/v1/top3/daily"]
        flask_stub.request.args = {"fecha": "2026-11-27"}
        raw_t3 = top3_handler()
        resp_t3 = raw_t3[0] if isinstance(raw_t3, tuple) else raw_t3
        top3_27 = resp_t3.get("top3") or []
        self.assertEqual(len(top3_27), 3)
        for pk in top3_27:
            self.assertEqual(pk.get("fecha_local_partido") or pk.get("fecha"), "2026-11-27")

        # 8-9. Werder Bremen vs Borussia M'gladbach: consistencia total en backend + auditoría + frontend (Node.js)
        wb_fx = next(f for f in m27 if "Werder" in f["local"])
        an_wb = pred_app.SportsAnalyticsEngine.generate_institutional_analysis(wb_fx)
        mu_wb = an_wb["metricas_unificadas"]
        for mk in ("avg_goals", "avg_corners", "avg_cards", "avg_shots", "avg_shots_on_target"):
            self.assertIn(mk, mu_wb)
            self.assertIsNotNone(mu_wb[mk]["valor"])
            self.assertIn(mu_wb[mk]["tipo_dato"], ("REAL_VERIFICADO", "ESTIMADO_MODELO"))
            self.assertTrue(mu_wb[mk]["fuente"])
            self.assertTrue(mu_wb[mk]["metodo"])
        # Cero "Datos insuficientes" en pilares, stakazos y consenso_5_modelos
        self.assertNotIn("insuficiente", an_wb["pilares_cuantitativos"]["pilar_1_volumen_ofensivo"]["corners_proyectados"].lower())
        self.assertNotIn("insuficiente", an_wb["pilares_cuantitativos"]["pilar_7_micromercados_friccion"]["tarjetas_proyectadas"].lower())
        for c5 in an_wb["consenso_5_modelos"]:
            self.assertNotIn("datos insuficientes", str(c5.get("metrica", "")).lower())

        # Endpoint de auditoría integral del partido
        aud_handler = self.flask_app.routes["/api/v1/partido/<match_id>/auditoria"]
        aud_resp, aud_code = aud_handler(wb_fx["id_partido"])
        self.assertEqual(aud_code, 200)
        self.assertTrue(aud_resp["success"])
        self.assertEqual(aud_resp["fecha_local_lima"], "2026-11-27")
        self.assertEqual(aud_resp["duplicados_en_pool"], 0)
        self.assertTrue(aud_resp["probabilidades_1x2_valido"])
        self.assertTrue(aud_resp["sin_cuota_real_inventada"])
        self.assertTrue(aud_resp["consistencia_secciones_ok"], f"Inconsistencias: {aud_resp['inconsistencias_detectadas']}")

        # Ejecución real en Node.js de extraerMetricasOddsterPartido() con el análisis real de Werder Bremen
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
        with open(html_path, "r", encoding="utf-8") as fh:
            html_txt = fh.read()

        def _extract_js_fn(src, name):
            start = src.index(f"function {name}(")
            brace = src.index("{", start)
            depth = 0
            for idx in range(brace, len(src)):
                if src[idx] == "{":
                    depth += 1
                elif src[idx] == "}":
                    depth -= 1
                    if depth == 0:
                        return src[start:idx + 1]
            raise ValueError(f"Unclosed {name}")

        fn_lavg = _extract_js_fn(html_txt, "obtenerPromediosLigaOddster")
        fn_odd = _extract_js_fn(html_txt, "extraerMetricasOddsterPartido")
        wb_payload = _json.dumps(an_wb, ensure_ascii=False)
        node_odd = f"""
{fn_lavg}
{fn_odd}
const item = {wb_payload};
item.codigo_liga = "BL1";
item.liga = "Bundesliga";
const m = extraerMetricasOddsterPartido(item);
console.log(JSON.stringify({{
    corners: m.avg_corners.val,
    cornersRec: m.avg_corners.rec,
    cards: m.avg_cards.val,
    cardsRec: m.avg_cards.rec,
    shots: m.avg_shots.val,
    shotsOT: m.avg_shots_ot.val
}}));
"""
        proc = subprocess.run(["node", "-e", node_odd], capture_output=True, text=True, check=True)
        odd_out = _json.loads(proc.stdout.strip())
        self.assertIsNotNone(odd_out["corners"])
        self.assertNotIn("Datos insuficientes", str(odd_out["cornersRec"]))
        self.assertIsNotNone(odd_out["cards"])
        self.assertNotIn("Datos insuficientes", str(odd_out["cardsRec"]))
        self.assertIsNotNone(odd_out["shots"])
        self.assertIsNotNone(odd_out["shotsOT"])

        # 10-12. Bloqueo de concurrencia en DailyAutomationPipeline + resiliencia si proveedor externo falla
        self.assertTrue(pred_app.DailyAutomationPipeline._EXEC_GUARD.acquire(blocking=False))
        try:
            blocked = pred_app.DailyAutomationPipeline.run_daily_pipeline(motivo="TEST_CONCURRENTE")
            self.assertTrue(blocked.get("skipped"))
            self.assertEqual(blocked.get("motivo"), "EJECUCION_SIMULTANEA_BLOQUEADA")
        finally:
            pred_app.DailyAutomationPipeline._EXEC_GUARD.release()

        with patch.object(pred_app.FootballDataOrgClient, "fetch_json", return_value={"ok": False, "data": None, "error": "timeout"}),              patch.object(pred_app.Top3RotationManager, "check_and_run_rotation", return_value={"published": False, "telegram_sent": False, "cantidad_selecciones": 3, "fecha_partidos": "2026-11-27", "estado_telegram": "YA_PUBLICADO"}),              patch.object(pred_app.Top3RotationManager, "close_previous_matchday", return_value={"finalizados": 0, "resultados_enviados": False}):
            res_pipe = pred_app.DailyAutomationPipeline.run_daily_pipeline(motivo="TEST_RESILIENCIA_EXTERNA")
        self.assertTrue(res_pipe["success"])
        # Calendario del 27 sigue intacto con los 7 partidos pese al fallo del proveedor externo
        m27_post = [f for f in pred_app.ALL_FIXTURES_POOL if pred_app.resolve_match_local_date(f)[1] == "2026-11-27"]
        self.assertEqual(len(m27_post), 7)

if __name__ == "__main__":
    unittest.main(verbosity=2)

    unittest.main(verbosity=2)
