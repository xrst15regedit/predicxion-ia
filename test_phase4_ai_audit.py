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
            self.assertEqual(len(todos), 10, "Deben estar presentes las 10 competiciones en /obtener-pronostico")
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
            self.assertGreater(total_checked, 400)

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
            self.assertIsNone(m_obj["valor"])
            self.assertEqual(m_obj["tipo_dato"], "ESTIMADO_MODELO")
            self.assertEqual(m_obj["muestra_n"], 0)
            self.assertEqual(m_obj["mensaje_base"], "Sin base suficiente para estimar")
            self.assertEqual(m_obj["etiqueta_ui"], "No estimable")
            self.assertEqual(m_obj["recommended_modelado"], "Sin base suficiente para estimar")

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

        # Verificar que index.html reemplazó N/D por "Estimación del modelo" y "No estimable"
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("N/D", html)
        self.assertIn("Estimación del modelo", html)
        self.assertIn("No estimable", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)

    unittest.main(verbosity=2)
