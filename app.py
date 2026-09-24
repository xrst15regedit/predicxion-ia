# ======================================================================================
# ARCHIVO: app.py
# DESCRIPCIÓN: Backend Cuantitativo PredicXion IA
# SERVICIOS: API REST, Sincronización Football-Data.org, Motor Poisson Multidimensión,
#            Gestión de Suscripciones y Registro de Auditoría
# ======================================================================================

import os
import sys
import re
import math
import time
import json
import logging
import threading
from datetime import datetime, timedelta, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import numpy as np
from flask import Flask, request, jsonify, g, send_file, render_template, Response
from flask_cors import CORS

# --------------------------------------------------------------------------------------
# CARGA DE VARIABLES DE ENTORNO
# --------------------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except (ImportError, ModuleNotFoundError):
    pass

import firebase_admin
from firebase_admin import credentials, firestore, auth

# --------------------------------------------------------------------------------------
# 1. CONFIGURACIÓN DE REGISTROS (LOGS)
# --------------------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] -> %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("PredicXionCore")

OWNER_EMAILS = {"fabiancermaz@gmail.com"}

# --------------------------------------------------------------------------------------
# 2. INICIALIZACIÓN DE BASE DE DATOS (FIRESTORE)
# --------------------------------------------------------------------------------------
def init_firebase():
    try:
        if not firebase_admin._apps:
            secret_path = "/etc/secrets/FIREBASE_CREDENTIALS_JSON"
            local_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
            
            if os.path.exists(secret_path):
                cred = credentials.Certificate(secret_path)
                firebase_admin.initialize_app(cred)
            elif local_path and os.path.isfile(local_path):
                cred = credentials.Certificate(local_path)
                firebase_admin.initialize_app(cred)
            else:
                firebase_admin.initialize_app()
        return firestore.client()
    except Exception as exc:
        logger.error("Error al inicializar Firebase Admin SDK: %s", exc)
        raise exc

db = init_firebase()

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "")

# --------------------------------------------------------------------------------------
# 3. CAPA DE AUTENTICACIÓN Y SEGURIDAD
# --------------------------------------------------------------------------------------
def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", None)
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({
                "success": False,
                "error": "Acceso denegado: Token de autorización ausente o inválido."
            }), 401
        
        token = auth_header.split("Bearer ")[1].strip()
        try:
            decoded_token = auth.verify_id_token(token)
            g.user_id = decoded_token.get("uid")
            g.user_email = (decoded_token.get("email") or "").lower()
            g.user_claims = decoded_token
        except Exception as exc:
            logger.warning("Token de Firebase inválido: %s", exc)
            return jsonify({
                "success": False,
                "error": "Token de autenticación expirado o inválido."
            }), 401
        return f(*args, **kwargs)
    return decorated

def require_subscription(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = getattr(g, "user_id", None)
        user_email = getattr(g, "user_email", None)

        if user_email in OWNER_EMAILS:
            g.is_owner = True
            return f(*args, **kwargs)

        g.is_owner = False
        if not user_id:
            return jsonify({"success": False, "error": "Identidad no verificada."}), 401

        try:
            doc = db.collection("usuarios").document(user_id).get()
            if not doc.exists:
                return jsonify({
                    "success": False,
                    "error": "Usuario sin suscripción activa registrada.",
                    "paywall": True
                }), 403

            data = doc.to_dict()
            activo = data.get("suscripcion_activa", False)
            expira = data.get("suscripcion_expira", None)

            valido = False
            if activo:
                if expira:
                    dt_expira = datetime.fromisoformat(expira) if isinstance(expira, str) else expira
                    if dt_expira > datetime.now(timezone.utc):
                        valido = True
                else:
                    valido = True

            if not valido:
                return jsonify({
                    "success": False,
                    "error": "Acceso restringido: Requiere Membresía Pro activa.",
                    "paywall": True
                }), 403
        except Exception as exc:
            logger.error("Error verificando suscripción para %s: %s", user_id, exc)
            return jsonify({"success": False, "error": "Error interno validando credenciales."}), 500

        return f(*args, **kwargs)
    return decorated

# --------------------------------------------------------------------------------------
# 4. MOTOR CUANTITATIVO MATEMÁTICO (POISSON Y KELLY REAL)
# --------------------------------------------------------------------------------------
class SportsAnalyticsEngine:
    @staticmethod
    def calculate_poisson(k: int, lamb: float) -> float:
        if lamb <= 0:
            return 1.0 if k == 0 else 0.0
        return (math.pow(lamb, k) * math.exp(-lamb)) / math.factorial(k)

    @classmethod
    def evaluate_match_probabilities(cls, lambda_home: float, lambda_away: float, max_goals: int = 7) -> dict:
        """
        Calcula la matriz de probabilidades de goles independientes para ambos equipos.
        """
        if lambda_home <= 0 or lambda_away <= 0:
            lambda_home = max(0.2, lambda_home)
            lambda_away = max(0.2, lambda_away)

        matrix = np.zeros((max_goals + 1, max_goals + 1))
        for i in range(max_goals + 1):
            p_i = cls.calculate_poisson(i, lambda_home)
            for j in range(max_goals + 1):
                matrix[i, j] = p_i * cls.calculate_poisson(j, lambda_away)

        total = float(matrix.sum())
        if total > 0:
            matrix /= total

        # Resultados 1X2
        prob_h = float(np.sum(np.tril(matrix, -1)))
        prob_d = float(np.sum(np.diag(matrix)))
        prob_a = float(np.sum(np.triu(matrix, 1)))

        # Mercados complementarios
        prob_under_2_5 = float(sum(matrix[i, j] for i in range(max_goals + 1) for j in range(max_goals + 1) if i + j <= 2))
        prob_btts = float(np.sum(matrix[1:, 1:]))

        return {
            "1X2": {
                "1": round(prob_h * 100, 2),
                "X": round(prob_d * 100, 2),
                "2": round(prob_a * 100, 2)
            },
            "over_under_2_5": {
                "over": round((1.0 - prob_under_2_5) * 100, 2),
                "under": round(prob_under_2_5 * 100, 2)
            },
            "btts": {
                "yes": round(prob_btts * 100, 2),
                "no": round((1.0 - prob_btts) * 100, 2)
            },
            "fair_odds": {
                "1": round(1.0 / prob_h, 2) if prob_h > 0 else None,
                "X": round(1.0 / prob_d, 2) if prob_d > 0 else None,
                "2": round(1.0 / prob_a, 2) if prob_a > 0 else None
            }
        }

    @staticmethod
    def evaluate_kelly_stake(prob_percent: float, market_odds: float, bankroll: float = 1000.0) -> dict:
        if market_odds <= 1.0 or prob_percent <= 0:
            return {"ev_percent": 0.0, "value_detected": False, "stake_percent": 0.0, "recommended_amount": 0.0}

        p = prob_percent / 100.0
        implied_p = 1.0 / market_odds
        edge = p - implied_p
        ev = (p * market_odds) - 1.0

        b = market_odds - 1.0
        q = 1.0 - p
        full_kelly = (b * p - q) / b if b > 0 else 0.0
        fractional_kelly = max(0.0, full_kelly * 0.25)
        
        has_value = ev > 0 and edge >= 0.02
        stake_pct = min(2.5, round(fractional_kelly * 100, 2)) if has_value else 0.0

        return {
            "ev_percent": round(ev * 100, 2),
            "edge_percent": round(edge * 100, 2),
            "value_detected": has_value,
            "stake_percent": stake_pct,
            "recommended_amount": round(bankroll * (stake_pct / 100.0), 2)
        }

# --------------------------------------------------------------------------------------
# 5. WORKER ETL REAL: FOOTBALL-DATA.ORG
# --------------------------------------------------------------------------------------
class FootballDataETL:
    FREE_TIER_COMPETITIONS = ["PL", "PD", "SA", "BL1", "FL1", "DED", "PPL", "CL", "BSA"]

    def __init__(self):
        self.lock = threading.Lock()
        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504))
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def run_sync(self):
        if not self.lock.acquire(blocking=False):
            logger.warning("ETL ya se encuentra en ejecución activa.")
            return False

        try:
            api_key = os.getenv("FOOTBALL_API_KEY")
            if not api_key:
                logger.error("FOOTBALL_API_KEY ausente. Configúrala en las variables de entorno.")
                return False

            now = datetime.now(timezone.utc)
            date_from = now.strftime("%Y-%m-%d")
            date_to = (now + timedelta(days=30)).strftime("%Y-%m-%d")

            headers = {"X-Auth-Token": api_key}
            url = "https://api.football-data.org/v4/matches"
            
            logger.info("Sincronizando partidos desde Football-Data.org (%s a %s)...", date_from, date_to)
            resp = self.session.get(
                url,
                headers=headers,
                params={"dateFrom": date_from, "dateTo": date_to},
                timeout=15
            )

            if resp.status_code == 429:
                logger.warning("Rate limit alcanzado en Football-Data.org. Reintentar en 60 segundos.")
                return False

            resp.raise_for_status()
            data = resp.json()
            matches = data.get("matches", [])

            saved_count = 0
            batch = db.batch()

            for m in matches:
                comp_code = (m.get("competition") or {}).get("code")
                # Filtrar solo ligas soportadas
                if comp_code and comp_code not in self.FREE_TIER_COMPETITIONS:
                    continue

                match_id = str(m.get("id"))
                home_team = (m.get("homeTeam") or {}).get("name")
                away_team = (m.get("awayTeam") or {}).get("name")

                if not home_team or not away_team:
                    continue

                doc_data = {
                    "id_partido": match_id,
                    "liga": (m.get("competition") or {}).get("name", "Liga Internacional"),
                    "codigo_liga": comp_code,
                    "local": home_team,
                    "visitante": away_team,
                    "logo_local": (m.get("homeTeam") or {}).get("crest"),
                    "logo_visitante": (m.get("awayTeam") or {}).get("crest"),
                    "fecha_utc": m.get("utcDate"),
                    "estado": m.get("status", "SCHEDULED"),
                    "marcador": m.get("score") or {},
                    "actualizado_en": firestore.SERVER_TIMESTAMP,
                    "source_provider": "football-data.org"
                }

                doc_ref = db.collection("partidos_verificados").document(match_id)
                batch.set(doc_ref, doc_data, merge=True)
                saved_count += 1

                if saved_count % 400 == 0:
                    batch.commit()
                    batch = db.batch()

            if saved_count > 0:
                batch.commit()

            logger.info("Sincronización completada: %d partidos oficiales guardados.", saved_count)
            return True

        except Exception as exc:
            logger.error("Error en sincronización ETL: %s", exc)
            return False
        finally:
            self.lock.release()

etl_service = FootballDataETL()

# --------------------------------------------------------------------------------------
# 6. FÁBRICA DE APLICACIÓN FLASK
# --------------------------------------------------------------------------------------
def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app, resources={r"/*": {"origins": "*"}})
    analytics = SportsAnalyticsEngine()

    # Registro de Blueprints
    try:
        from routes import matches_bp
        app.register_blueprint(matches_bp)
        logger.info("Blueprint matches_bp registrado exitosamente.")
    except Exception as e:
        logger.warning("No se pudo registrar matches_bp: %s", e)

    # Servir Frontend
    @app.route("/", methods=["GET"])
    def serve_frontend_index():
        base_dir = os.path.dirname(os.path.abspath(__file__))
        rutas = [
            os.path.join(base_dir, "templates", "index.html"),
            os.path.join(base_dir, "index.html")
        ]
        for r in rutas:
            if os.path.exists(r):
                return send_file(r)
        return render_template("index.html")

    # Cartelera de Partidos Reales
    @app.route("/obtener-pronostico", methods=["GET"])
    def obtener_pronostico():
        try:
            now = datetime.now(timezone.utc)
            now_iso = now.isoformat()
            limit_iso = (now + timedelta(days=30)).isoformat()

            docs = list(db.collection("partidos_verificados")
                          .where("fecha_utc", ">=", now_iso)
                          .where("fecha_utc", "<=", limit_iso)
                          .order_by("fecha_utc")
                          .limit(100)
                          .stream())

            todos = {}
            destacados = []

            for d in docs:
                m = d.to_dict()
                liga = m.get("liga", "Otras Ligas")

                # Estimación de parámetros Poisson basados en medias competitivas
                # (1.45 goles promedio local / 1.15 goles promedio visitante)
                lh = float(m.get("lambda_home", 1.45))
                la = float(m.get("lambda_away", 1.15))
                probs = analytics.evaluate_match_probabilities(lh, la)

                # Determinar selección cuantitativa principal (mayor probabilidad calculada)
                p1x2 = probs["1X2"]
                if p1x2["1"] >= p1x2["X"] and p1x2["1"] >= p1x2["2"]:
                    pick_sel = m["local"]
                    pick_prob = p1x2["1"]
                elif p1x2["2"] >= p1x2["1"] and p1x2["2"] >= p1x2["X"]:
                    pick_sel = m["visitante"]
                    pick_prob = p1x2["2"]
                else:
                    pick_sel = "Empate"
                    pick_prob = p1x2["X"]

                item = {
                    "id_partido": m.get("id_partido", d.id),
                    "partido": f"{m['local']} vs {m['visitante']}",
                    "local": m["local"],
                    "visitante": m["visitante"],
                    "liga": liga,
                    "fecha": m["fecha_utc"][:16].replace("T", " "),
                    "estado": m.get("estado", "SCHEDULED"),
                    "probabilidades": probs,
                    "pronostico_principal": {
                        "seleccion": pick_sel,
                        "probabilidad": f"{pick_prob}%",
                        "fair_odds": probs["fair_odds"]
                    }
                }

                todos.setdefault(liga, []).append(item)
                if len(destacados) < 8 and m.get("estado") == "SCHEDULED":
                    destacados.append(item)

            return jsonify({
                "success": True,
                "todos_los_partidos": todos,
                "total_partidos": sum(len(v) for v in todos.values()),
                "pronosticos_destacados": destacados,
                "data_source": "Partidos sincronizados oficialmente desde Football-Data.org"
            }), 200

        except Exception as exc:
            logger.error("Error al obtener cartelera: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    # Análisis Profundo Cuantitativo
    @app.route("/api/v1/matches/<match_id>/analysis", methods=["GET"])
    @require_auth
    def get_match_deep_analysis(match_id: str):
        try:
            doc = db.collection("partidos_verificados").document(match_id).get()
            if not doc.exists:
                return jsonify({"success": False, "error": "Partido no encontrado en la base de datos."}), 404

            m = doc.to_dict()
            lh = float(m.get("lambda_home", 1.45))
            la = float(m.get("lambda_away", 1.15))
            probs = analytics.evaluate_match_probabilities(lh, la)

            # Análisis de valor sobre cuotas observadas (si existen) o cuotas justas
            cuotas = m.get("cuotas", {})
            odds_1 = float(cuotas.get("1", probs["fair_odds"]["1"]))
            val_eval = analytics.evaluate_kelly_stake(probs["1X2"]["1"], odds_1)

            analysis = {
                "id_partido": match_id,
                "partido": f"{m['local']} vs {m['visitante']}",
                "fecha": m.get("fecha_utc"),
                "probabilidades": probs,
                "evaluacion_valor": val_eval,
                "parametros_modelo": {
                    "lambda_local": lh,
                    "lambda_visitante": la,
                    "modelo": "Distribución Poisson Bivariada Determinista"
                }
            }
            return jsonify({"success": True, "data": analysis}), 200

        except Exception as exc:
            logger.error("Error en deep analysis: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    # Pagos Manuales (Yape / Plin) - Seguridad sin autoaprobación indiscriminada
    @app.route("/api/v1/payments/manual-submit", methods=["POST"])
    @require_auth
    def process_manual_payment():
        try:
            body = request.get_json() or {}
            metodo = body.get("metodo", "").lower()
            telefono = str(body.get("telefono", "")).strip()
            codigo = str(body.get("codigo", "")).strip()
            plan_texto = body.get("plan_texto", "Mensual Pro")
            monto = float(body.get("monto", 39.90))

            if metodo not in ["yape", "plin"]:
                return jsonify({"success": False, "error": "Método no soportado."}), 400

            if not re.match(r"^9\d{8}$", telefono):
                return jsonify({"success": False, "error": "Número celular inválido (9 dígitos requeridos)."}), 400

            if not codigo or len(codigo) < 4:
                return jsonify({"success": False, "error": "Código de operación requerido."}), 400

            operacion_id = f"{metodo.upper()}-{int(time.time())}"
            pago_record = {
                "usuario_id": g.user_id,
                "email": g.user_email,
                "metodo": metodo.upper(),
                "telefono": telefono,
                "codigo_operacion": codigo,
                "monto": monto,
                "plan": plan_texto,
                "estado": "PENDIENTE_REVISION",  # Requiere confirmación de abono real
                "fecha_utc": datetime.now(timezone.utc).isoformat()
            }
            db.collection("pagos_manuales").document(operacion_id).set(pago_record)

            return jsonify({
                "success": True,
                "message": "Comprobante recibido. La suscripción se activará una vez verificado el depósito.",
                "operacion_id": operacion_id,
                "estado": "PENDIENTE_REVISION"
            }), 200

        except Exception as exc:
            logger.error("Error en pago manual: %s", exc)
            return jsonify({"success": False, "error": "Error al registrar el pago."}), 500

    # Endpoint para disparar el ETL de sincronización
    @app.route("/api/v1/admin/etl/trigger", methods=["POST"])
    @require_auth
    def trigger_etl():
        if g.user_email not in OWNER_EMAILS:
            return jsonify({"error": "No autorizado."}), 403

        threading.Thread(target=etl_service.run_sync).start()
        return jsonify({"success": True, "message": "Sincronización iniciada en segundo plano."}), 202

    # Health Check
    @app.route("/api/v1/health", methods=["GET"])
    def health_check():
        return jsonify({
            "status": "OPERATIONAL",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 200

    return app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
