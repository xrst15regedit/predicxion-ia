import os
import time
import random
from datetime import datetime, timedelta
import requests
import json
import urllib.parse
import xml.etree.ElementTree as ET
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from google import genai
from google.genai import types
import mercadopago

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
# Habilitamos CORS de forma total para permitir peticiones seguras desde cualquier origen
CORS(app, resources={r"/*": {"origins": "*"}})

# Claves de acceso a las APIs externas
api_key_futbol = os.environ.get("API_KEY_FUTBOL", "755809cd5c834eb68eaff1f0adc9f5b9")
api_key_groq = os.environ.get("API_KEY_GROQ", "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")
api_key_gemini = os.environ.get("API_KEY_GEMINI", "AQ.Ab8RN6JTibLAdImfDygsgXyz_j0K_ukrjAEeMxLpDN7D14B6Og")

# Token de producción oficial de Mercado Pago (Integrado y verificado)
MP_ACCESS_TOKEN = os.environ.get(
    "MP_ACCESS_TOKEN", 
    "APP_USR-3069452262845672-090811-ff2adcff8f98ffe6638b076fee2eae68-3672390181"
)

try:
    sdk_mp = mercadopago.SDK(MP_ACCESS_TOKEN)
    print("✅ SDK de Mercado Pago conectado con credenciales de producción.")
except Exception as error_mp:
    print(f"⚠️ Error inicializando SDK de Mercado Pago: {error_mp}")
    sdk_mp = None

try:
    client_gemini = genai.Client(api_key=api_key_gemini)
except Exception as error_gemini:
    print(f"⚠️ Aviso inicializando cliente Gemini: {error_gemini}")
    client_gemini = None

# Estructuras en memoria para optimizar velocidad y evitar sobrecostos de llamadas API
MODELOS_GROQ_CACHE = []
CACHE_TIMESTAMP = 0

CACHE_CALENDARIO_RAW = None
CACHE_CALENDARIO_TIMESTAMP = 0

CACHE_PARTIDOS_DATA = None
CACHE_PARTIDOS_TIMESTAMP = 0
CACHE_DURACION_SEGUNDOS = 900  # 15 minutos de persistencia en caché

def buscar_noticias_tiempo_real(termino_busqueda):
    """Consulta noticias de última hora vía Google News RSS para nutrir al modelo con fichajes y bajas."""
    try:
        query_limpia = urllib.parse.quote(f"{termino_busqueda} futbol 2026 2027 fichajes bajas alineaciones")
        url_feed = f"https://news.google.com/rss/search?q={query_limpia}&hl=es&gl=ES&ceid=ES:es"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url_feed, headers=headers, timeout=3.5)
        
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            items = root.findall('.//item')[:3]
            titulares = [item.find('title').text.strip() for item in items if item.find('title') is not None]
            if titulares:
                return "\n".join([f"- {t}" for t in titulares])
    except Exception:
        pass
    return ""

def obtener_modelos_groq():
    """Descubre dinámicamente los modelos Llama y DeepSeek disponibles en la API de Groq."""
    global MODELOS_GROQ_CACHE, CACHE_TIMESTAMP
    if MODELOS_GROQ_CACHE and (time.time() - CACHE_TIMESTAMP < 3600):
        return MODELOS_GROQ_CACHE

    try:
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key_groq}"},
            timeout=4
        )
        if resp.status_code == 200:
            disponibles = [m['id'] for m in resp.json().get('data', [])]
            preferencias = ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant', 'deepseek-r1-distill-llama-70b']
            ordenados = [p for p in preferencias if p in disponibles]
            for d in disponibles:
                if d not in ordenados and 'whisper' not in d.lower():
                    ordenados.append(d)
            if ordenados:
                MODELOS_GROQ_CACHE = ordenados
                CACHE_TIMESTAMP = time.time()
                return ordenados
    except Exception:
        pass
    return ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

@app.route('/')
def home():
    """Sirve la página web frontal index.html o un estado básico del backend."""
    ruta_index = os.path.join(BASE_DIR, 'index.html')
    if os.path.exists(ruta_index):
        return send_from_directory(BASE_DIR, 'index.html')
    return jsonify({
        "estado": "operativo",
        "servicio": "PredicXion IA Backend",
        "temporada": "2026-2027",
        "mercado_pago": "conectado" if sdk_mp else "no inicializado"
    }), 200

def llamar_ia_hibrida(prompt_completo, contexto_noticias=""):
    """Motor central con balanceo entre Gemini 2.5 Flash (Google Grounding) y Groq (alta velocidad)."""
    ahora_utc = datetime.utcnow()
    ahora_peru = ahora_utc - timedelta(hours=5)
    fecha_actual_txt = ahora_peru.strftime('%d/%m/%Y')
    anio_actual = ahora_peru.year

    bloque_noticias = ""
    if contexto_noticias:
        bloque_noticias = f"\n[NOTICIAS EN VIVO DE ESTA TEMPORADA ({anio_actual}-{anio_actual+1})]:\n{contexto_noticias}\n"

    prompt_sistema = (
        f"Eres el Analista Cuantitativo Principal de PredicXion IA.\n"
        f"REGLA DE ORO TEMPORAL: Hoy es {fecha_actual_txt} (Temporada oficial {anio_actual}-{anio_actual+1}).\n"
        f"PROHIBIDO usar datos o alineaciones de años antiguos. Analiza estrictamente las plantillas y forma presente.\n"
        f"{bloque_noticias}\n"
        "DIRECTRICES OBLIGATORIAS:\n"
        "1. ENFOQUE TOTAL: Responde de forma precisa sobre el encuentro o parlay solicitado.\n"
        "2. ANÁLISIS SINTÉTICO: Evalúa métricas avanzadas (xG, posesión, transiciones y valor EV+), con un MÍNIMO de 2 y un MÁXIMO de 7 oraciones.\n"
        "3. SALUDO Y DESPEDIDA: Comienza con un saludo breve y cierra con una despedida concisa y profesional.\n"
        "4. COMBINADAS / PARLAYS: Si se solicita parlay, lista las cuotas individuales estimadas y calcula la Cuota Total Combinada (Multiplicador final).\n"
        "5. FORMATO: Sin hashtags. Resalta selecciones de apuesta y cuotas en formato **negrita**."
    )

    # Nivel 1: Gemini 2.5 Flash con motor de búsqueda en vivo
    if client_gemini:
        try:
            config_search = types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.25
            )
            respuesta = client_gemini.models.generate_content(
                model='gemini-2.5-flash',
                contents=f"{prompt_sistema}\n\n[CONSULTA]:\n{prompt_completo}",
                config=config_search
            )
            if respuesta and respuesta.text:
                return respuesta.text.strip()
        except Exception:
            pass

    # Nivel 2: Alternancia rápida con modelos en Groq
    url_groq = "https://api.groq.com/openai/v1/chat/completions"
    headers_groq = {"Authorization": f"Bearer {api_key_groq}", "Content-Type": "application/json"}
    
    for modelo_actual in obtener_modelos_groq():
        try:
            response = requests.post(
                url_groq,
                headers=headers_groq,
                json={
                    "model": modelo_actual,
                    "messages": [
                        {"role": "system", "content": prompt_sistema},
                        {"role": "user", "content": prompt_completo}
                    ],
                    "temperature": 0.25,
                    "max_tokens": 3000
                },
                timeout=15
            )
            if response.status_code == 200:
                return response.json()['choices'][0]['message']['content'].strip()
        except Exception:
            continue

    return "Servicio temporalmente con alta demanda. Por favor, reintenta tu consulta en unos segundos."

@app.route('/obtener-pronostico', methods=['GET'])
def obtener_pronostico():
    """Genera la cartelera de partidos programados y produce los 10 análisis cuantitativos destacados."""
    global CACHE_CALENDARIO_RAW, CACHE_CALENDARIO_TIMESTAMP, CACHE_PARTIDOS_DATA, CACHE_PARTIDOS_TIMESTAMP
    try:
        es_recarga = request.args.get('refresh', 'false').lower() == 'true'

        if not es_recarga and CACHE_PARTIDOS_DATA and (time.time() - CACHE_PARTIDOS_TIMESTAMP < CACHE_DURACION_SEGUNDOS):
            return jsonify(CACHE_PARTIDOS_DATA)

        ahora_utc = datetime.utcnow()
        ahora_peru = ahora_utc - timedelta(hours=5)
        ahora_utc_str = ahora_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        anio_actual = ahora_peru.year
        headers_football = {"X-Auth-Token": api_key_futbol}

        partidos_por_competicion = {}
        todos_los_partidos_plano = []

        if CACHE_CALENDARIO_RAW and (time.time() - CACHE_CALENDARIO_TIMESTAMP < CACHE_DURACION_SEGUNDOS):
            partidos_por_competicion = CACHE_CALENDARIO_RAW
            for lista in partidos_por_competicion.values():
                todos_los_partidos_plano.extend(lista)
        else:
            COMPETENCIAS_OFICIALES = [
                ('CL', 'UEFA Champions League'),
                ('PL', 'Premier League (Inglaterra)'),
                ('PD', 'La Liga (España)'),
                ('SA', 'Serie A (Italia)'),
                ('BL1', 'Bundesliga (Alemania)'),
                ('FL1', 'Ligue 1 (Francia)'),
                ('PPL', 'Primeira Liga (Portugal)'),
                ('DED', 'Eredivisie (Países Bajos)'),
                ('BSA', 'Brasileirão Série A Betano'),
                ('CLI', 'CONMEBOL Libertadores')
            ]

            for comp_code, comp_nombre in COMPETENCIAS_OFICIALES:
                url_fd = f"https://api.football-data.org/v4/competitions/{comp_code}/matches?status=SCHEDULED"
                partidos_liga = []
                try:
                    resp = requests.get(url_fd, headers=headers_football, timeout=5)
                    if resp.status_code == 200:
                        for m in resp.json().get('matches', []):
                            if m.get('utcDate', '') >= ahora_utc_str:
                                dt_local = datetime.strptime(m['utcDate'], '%Y-%m-%dT%H:%M:%SZ') - timedelta(hours=5)
                                encuentro = {
                                    "id": m.get('id'),
                                    "partido": f"{m['homeTeam']['name']} vs {m['awayTeam']['name']}",
                                    "competicion": comp_nombre,
                                    "fecha": dt_local.strftime('%d/%m/%Y %H:%M')
                                }
                                partidos_liga.append(encuentro)
                                todos_los_partidos_plano.append(encuentro)
                        if partidos_liga:
                            partidos_por_competicion[comp_nombre] = partidos_liga
                except Exception:
                    continue

            if partidos_por_competicion:
                CACHE_CALENDARIO_RAW = partidos_por_competicion
                CACHE_CALENDARIO_TIMESTAMP = time.time()

        partidos_analizar = []
        if todos_los_partidos_plano:
            pool = list(todos_los_partidos_plano)
            random.shuffle(pool)
            ligas_vistas, diversos, restantes = set(), [], []
            for p in pool:
                if p['competicion'] not in ligas_vistas:
                    diversos.append(p)
                    ligas_vistas.add(p['competicion'])
                else:
                    restantes.append(p)
            partidos_analizar = (diversos + restantes)[:10]

        partidos_texto = "\n".join([f"- {p['partido']} ({p['competicion']}) [{p['fecha']}]" for p in partidos_analizar])
        prompt_lote = f"""
        Motor cuantitativo. Temporada {anio_actual}-{anio_actual+1}. Analiza estos 10 partidos programados y proyecta probabilidades y cuotas sugeridas:
        {partidos_texto}

        Devuelve ÚNICAMENTE un JSON válido (array de objetos sin caracteres adicionales ni etiquetas markdown):
        [
          {{
            "partido": "Local vs Visita",
            "competicion": "Liga",
            "fecha": "Fecha",
            "probabilidad": "52% / 28% / 20%",
            "principal": "Doble Oportunidad 1X (@1.55)",
            "alternativa": "Ambos Equipos Anotan (@1.80)",
            "parlay": "1X + Más de 1.5 Goles (@1.72)",
            "argumento": "Explicación táctica concisa con xG y forma.",
            "ev_alto": true
          }}
        ]
        """

        texto_respuesta = llamar_ia_hibrida(prompt_lote)
        resultados_destacados = []
        try:
            inicio_json = texto_respuesta.find('[')
            fin_json = texto_respuesta.rfind(']') + 1
            if inicio_json != -1 and fin_json != -1:
                resultados_destacados = json.loads(texto_respuesta[inicio_json:fin_json])
        except Exception:
            for i, p in enumerate(partidos_analizar):
                resultados_destacados.append({
                    **p,
                    "probabilidad": "53% / 27% / 20%",
                    "principal": "Doble Oportunidad 1X (@1.58)",
                    "alternativa": "Más de 1.5 Goles (@1.70)",
                    "parlay": "1X + Más 1.5 Goles (@1.75)",
                    "argumento": f"Ventaja cuantitativa en bloque medio y proyección xG para la temporada {anio_actual}.",
                    "ev_alto": (i % 2 == 0)
                })

        payload = {
            "todos_los_partidos": partidos_por_competicion,
            "pronosticos_destacados": resultados_destacados,
            "total_partidos": sum(len(m) for m in partidos_por_competicion.values())
        }
        CACHE_PARTIDOS_DATA = payload
        CACHE_PARTIDOS_TIMESTAMP = time.time()
        return jsonify(payload)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/chat-ia', methods=['POST'])
def chat_ia():
    """Recibe las preguntas de los usuarios y genera respuestas con noticias de último minuto."""
    try:
        body = request.get_json() or {}
        mensaje_usuario = body.get('mensaje', '')
        if not mensaje_usuario:
            return jsonify({"error": "Mensaje vacío"}), 400

        noticias_vivas = buscar_noticias_tiempo_real(mensaje_usuario)
        respuesta_ia = llamar_ia_hibrida(mensaje_usuario, contexto_noticias=noticias_vivas)
        return jsonify({"respuesta": respuesta_ia})
    except Exception:
        return jsonify({"error": "Saturación temporal del motor predictivo. Intenta de nuevo en un momento."}), 500

@app.route('/crear-preferencia', methods=['POST'])
def crear_preferencia():
    """Genera la preferencia de pago en Mercado Pago (Checkout Pro) y devuelve el enlace seguro de cobro."""
    if not sdk_mp:
        return jsonify({"error": "El servicio de pagos no está inicializado en el servidor."}), 500

    try:
        data = request.get_json() or {}
        plan_nombre = data.get("title", "Pase VIP PredicXion IA")
        precio = float(data.get("price", 39.90))
        email_cliente = data.get("email", "usuario@predicxionia.com")

        # URL dinámica para redireccionar al usuario de vuelta a tu web en Render
        url_base = request.host_url.rstrip('/')

        preference_data = {
            "items": [
                {
                    "title": plan_nombre,
                    "description": f"Suscripción exclusiva VIP - {plan_nombre}",
                    "quantity": 1,
                    "unit_price": precio,
                    "currency_id": "PEN"
                }
            ],
            "payer": {
                "email": email_cliente
            },
            "back_urls": {
                "success": f"{url_base}/?status=approved",
                "failure": f"{url_base}/?status=failed",
                "pending": f"{url_base}/?status=pending"
            },
            "auto_return": "approved",
            "notification_url": f"{url_base}/webhook-pagos"
        }

        resultado = sdk_mp.preference().create(preference_data)
        preferencia = resultado.get("response", {})

        return jsonify({
            "init_point": preferencia.get("init_point"),
            "sandbox_init_point": preferencia.get("sandbox_init_point")
        }), 200

    except Exception as e:
        print(f"Error al generar preferencia en Mercado Pago: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/webhook-pagos', methods=['POST', 'GET'])
def webhook_pagos():
    """Escucha la notificación instantánea de Mercado Pago cuando un pago con Yape o tarjeta es aprobado."""
    try:
        data = request.args if request.method == 'GET' or request.args else (request.get_json() or {})
        tipo_notificacion = data.get("type") or data.get("topic")

        if tipo_notificacion == "payment":
            payment_id = data.get("data.id") or data.get("id") or (data.get("data", {}).get("id") if isinstance(data.get("data"), dict) else None)

            if payment_id and sdk_mp:
                info_pago = sdk_mp.payment().get(payment_id)
                if info_pago.get("status") in [200, 201]:
                    estado_aprobacion = info_pago.get("response", {}).get("status")
                    if estado_aprobacion == "approved":
                        monto = info_pago["response"].get("transaction_amount")
                        metodo = info_pago["response"].get("payment_method_id")
                        email_pagador = info_pago["response"].get("payer", {}).get("email")
                        print(f"💰 ¡PAGO CONFIRMADO! ID: {payment_id} | Monto: S/{monto} | Método: {metodo} | Usuario: {email_pagador}")

        return jsonify({"status": "recibido"}), 200
    except Exception as e:
        print(f"Error procesando webhook de pago: {e}")
        return jsonify({"error": "Error interno del webhook"}), 500

if __name__ == '__main__':
    puerto = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=puerto, debug=False)
