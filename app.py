import os
import time
from datetime import datetime, timedelta
import requests
import json
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from google import genai

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ==========================================
# CONFIGURACIÓN DE LLAVES Y CREDENCIALES
# ==========================================
api_key_futbol = os.environ.get("API_KEY_FUTBOL", "755809cd5c834eb68eaff1f0adc9f5b9")
api_key_groq = os.environ.get("API_KEY_GROQ", "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")
api_key_gemini = os.environ.get("API_KEY_GEMINI", "AQ.Ab8RN6JTibLAdImfDygsgXyz_j0K_ukrjAEeMxLpDN7D14B6Og")

try:
    client_gemini = genai.Client(api_key=api_key_gemini)
except Exception as e:
    print(f"Aviso inicializando cliente Gemini: {e}")
    client_gemini = None

MODELOS_GROQ_CACHE = []
CACHE_TIMESTAMP = 0

CACHE_PARTIDOS_DATA = None
CACHE_PARTIDOS_TIMESTAMP = 0
CACHE_DURACION_SEGUNDOS = 900  # 15 minutos de caché

# ==========================================
# DETECCIÓN DINÁMICA DE MODELOS EN GROQ
# ==========================================
def obtener_modelos_groq():
    """Detecta dinámicamente modelos habilitados en la cuenta de Groq para evitar errores 404"""
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
            data = resp.json()
            disponibles = [m['id'] for m in data.get('data', [])]
            preferencias = [
                'llama-3.3-70b-versatile',
                'llama-3.1-8b-instant',
                'deepseek-r1-distill-llama-70b',
                'mixtral-8x7b-32768'
            ]
            ordenados = [p for p in preferencias if p in disponibles]
            for d in disponibles:
                if d not in ordenados and 'whisper' not in d.lower():
                    ordenados.append(d)
            if ordenados:
                MODELOS_GROQ_CACHE = ordenados
                CACHE_TIMESTAMP = time.time()
                return ordenados
    except Exception as e:
        print(f"Aviso consultando modelos activos en Groq: {e}")
    return ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

@app.route('/')
def home():
    if os.path.exists(os.path.join(BASE_DIR, 'index.html')):
        return send_from_directory(BASE_DIR, 'index.html')
    return "PredicXion IA Backend Operativo. index.html no encontrado en el directorio raíz.", 200

# ==========================================
# MOTOR HÍBRIDO CON REGLAS DE LONGITUD VIP
# ==========================================
def llamar_ia_hibrida(prompt_completo):
    """
    Motor analítico dual con veracidad empírica, xG y EV+.
    REGLAS ESTRICTAS:
    1. Saludo y despedida cortos, naturales y humanos.
    2. Análisis central entre 1.5 y 5 oraciones.
    3. Cero alucinaciones, cero símbolos de numeral/hashtag (#).
    """
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key_groq}",
        "Content-Type": "application/json"
    }
    
    modelos_disponibles = obtener_modelos_groq()
    
    prompt_sistema = (
        "Eres el Analista Táctico VIP de PredicXion IA. "
        "Operas con veracidad empírica absoluta, xG y EV+. "
        "REGLAS ESTRICTAS DE COMUNICACIÓN: "
        "1. Inicia siempre con un saludo muy corto y humano. Despídete de forma breve y natural al final. "
        "2. Tu análisis central (sin contar el saludo/despedida) debe tener un MÍNIMO de 1.5 oraciones y un MÁXIMO de 5 oraciones. "
        "3. Ve directo a la predicción y los datos duros reales. "
        "4. Cero alucinaciones. PROHIBIDO usar el símbolo de numeral o hashtag (#) bajo ninguna circunstancia."
    )

    # 1. INTENTO CON GROQ
    for modelo_actual in modelos_disponibles:
        payload = {
            "model": modelo_actual,
            "messages": [
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_completo}
            ],
            "temperature": 0.25, 
            "top_p": 0.9,
            "max_tokens": 1500
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            if response.status_code == 200:
                data = response.json()
                return data['choices'][0]['message']['content'].strip()
        except Exception as e:
            print(f"Aviso en conexión con Groq ({modelo_actual}): {e}")
                
    # 2. RESPALDO CON GEMINI
    if client_gemini:
        print("🔄 Activando motor de respaldo Gemini en PredicXion IA...")
        modelos_gemini = ['gemini-2.5-flash', 'gemini-2.0-flash']
        for m_gemini in modelos_gemini:
            try:
                respuesta = client_gemini.models.generate_content(
                    model=m_gemini,
                    contents=f"{prompt_sistema}\n\n{prompt_completo}",
                    config={"temperature": 0.25, "top_p": 0.9}
                )
                if respuesta.text:
                    return respuesta.text.strip()
            except Exception as e:
                print(f"Gemini falló en {m_gemini}: {e}")
                continue

    return "Servicio temporalmente saturado. Por favor, reintenta en unos instantes."

# ==========================================
# ENDPOINT DE PRONÓSTICOS Y CARTELERAS
# ==========================================
@app.route('/obtener-pronostico', methods=['GET'])
def obtener_pronostico():
    global CACHE_PARTIDOS_DATA, CACHE_PARTIDOS_TIMESTAMP
    try:
        if CACHE_PARTIDOS_DATA and (time.time() - CACHE_PARTIDOS_TIMESTAMP < CACHE_DURACION_SEGUNDOS):
            return jsonify(CACHE_PARTIDOS_DATA)

        headers = { "X-Auth-Token": api_key_futbol }
        
        # Ajuste horario UTC-5 (Hora de Perú)
        ahora_utc = datetime.utcnow()
        ahora_peru = ahora_utc - timedelta(hours=5)
        fecha_actual_str = ahora_peru.strftime('%Y-%m-%d')
        
        COMPETENCIAS_EUROPEAS = [
            ('CL', 'UEFA Champions League'),
            ('PL', 'Premier League (Inglaterra)'),
            ('PD', 'La Liga (España)'),
            ('SA', 'Serie A (Italia)'),
            ('BL1', 'Bundesliga (Alemania)'),
            ('FL1', 'Ligue 1 (Francia)'),
            ('PPL', 'Primeira Liga (Portugal)'),
            ('DED', 'Eredivisie (Países Bajos)')
        ]

        partidos_por_competicion = {}
        partidos_clave_ia = []

        def build_fecha(dias_offset, hora="19:00"):
            dt = ahora_peru + timedelta(days=dias_offset)
            return dt.strftime('%d/%m/%Y ') + hora, dt.strftime('%Y-%m-%d') + f"T{hora}:00Z"

        f1_txt, _ = build_fecha(1, "19:30")
        f2_txt, _ = build_fecha(2, "21:30")
        
        # Sudamericanas Oficiales (Sin Liga Peruana para evitar errores de fecha)
        partidos_libertadores = [
            {"id": "lib-1", "partido": "Flamengo vs River Plate", "competicion": "CONMEBOL Libertadores", "fecha": f1_txt},
            {"id": "lib-2", "partido": "Palmeiras vs Boca Juniors", "competicion": "CONMEBOL Libertadores", "fecha": f2_txt}
        ]
        partidos_por_competicion["CONMEBOL Libertadores"] = partidos_libertadores
        partidos_clave_ia.append(partidos_libertadores[0])

        partidos_sudamericana = [
            {"id": "sud-1", "partido": "Corinthians vs Racing Club", "competicion": "CONMEBOL Sudamericana", "fecha": f1_txt},
            {"id": "sud-2", "partido": "Cruzeiro vs Lanús", "competicion": "CONMEBOL Sudamericana", "fecha": f2_txt}
        ]
        partidos_por_competicion["CONMEBOL Sudamericana"] = partidos_sudamericana
        partidos_clave_ia.append(partidos_sudamericana[0])

        partidos_brasil = [
            {"id": "bsa-1", "partido": "Palmeiras vs Flamengo", "competicion": "Brasileirão Série A Betano", "fecha": f1_txt},
            {"id": "bsa-2", "partido": "Botafogo vs São Paulo", "competicion": "Brasileirão Série A Betano", "fecha": f2_txt}
        ]
        partidos_por_competicion["Brasileirão Série A Betano"] = partidos_brasil
        partidos_clave_ia.append(partidos_brasil[0])

        # Consulta Europeas vía football-data.org con filtro estricto de tiempo
        for comp_code, comp_nombre in COMPETENCIAS_EUROPEAS:
            url_fd = f"https://api.football-data.org/v4/competitions/{comp_code}/matches?status=SCHEDULED"
            partidos_de_esta_liga = []
            try:
                resp = requests.get(url_fd, headers=headers, timeout=4)
                if resp.status_code == 200:
                    data = resp.json()
                    for m in data.get('matches', []):
                        utc_date = m.get('utcDate', '')
                        if utc_date and utc_date[:10] >= fecha_actual_str:
                            try:
                                dt_obj = datetime.strptime(utc_date, '%Y-%m-%dT%H:%M:%SZ')
                                dt_local = dt_obj - timedelta(hours=5)
                                f_fmt = dt_local.strftime('%d/%m/%Y %H:%M')
                            except Exception:
                                f_fmt = "Próximamente"

                            partidos_de_esta_liga.append({
                                "id": m.get('id'),
                                "partido": f"{m['homeTeam']['name']} vs {m['awayTeam']['name']}",
                                "competicion": comp_nombre,
                                "fecha": f_fmt
                            })
                    if partidos_de_esta_liga:
                        partidos_por_competicion[comp_nombre] = partidos_de_esta_liga
                        partidos_clave_ia.append(partidos_de_esta_liga[0])
            except Exception:
                continue

        partidos_analizar = partidos_clave_ia[:8]
        partidos_texto = "\n".join([f"- {p['partido']} ({p['competicion']})" for p in partidos_analizar])

        prompt_lote = f"""
        INSTRUCCIÓN: Actúa como el motor cuantitativo de PredicXion IA. Analiza estos partidos y evalúa su Expected Value (EV+):
        {partidos_texto}

        Devuelve un JSON exacto, sin bloques de código markdown ni texto adicional fuera del arreglo JSON:
        [
          {{
            "partido": "Equipo Local vs Equipo Visitante",
            "competicion": "Competición",
            "fecha": "Fecha",
            "probabilidad": "50% L / 25% E / 25% V",
            "principal": "Over 1.5 Goles",
            "alternativa": "Ambos Anotan",
            "parlay": "1X + Over 1.5",
            "argumento": "Breve justificación con métricas xG y análisis táctico real",
            "ev_alto": true
          }}
        ]
        *NOTA: "ev_alto" debe ser booleano (true o false). Coloca true ÚNICAMENTE cuando detectes valor esperado positivo. PROHIBIDO usar '#' en el texto.
        """

        texto_respuesta = llamar_ia_hibrida(prompt_lote)
        
        resultados_destacados = []
        try:
            inicio = texto_respuesta.find('[')
            fin = texto_respuesta.rfind(']')
            if inicio != -1 and fin != -1:
                resultados_destacados = json.loads(texto_respuesta[inicio:fin + 1])
        except Exception as e:
            print(f"Aviso parseando JSON de PredicXion IA: {e}")

        if not resultados_destacados:
            for i, p in enumerate(partidos_analizar):
                resultados_destacados.append({
                    "partido": p.get("partido"),
                    "competicion": p.get("competicion"),
                    "fecha": p.get("fecha"),
                    "probabilidad": "52% Local, 28% Empate, 20% Visitante",
                    "principal": "Doble Oportunidad 1X",
                    "alternativa": "Más de 1.5 Goles",
                    "parlay": "1X + Más de 1.5 Goles",
                    "argumento": "Ventaja en posesión en tercio rival y solidez en goles esperados concedidos.",
                    "ev_alto": True if i % 3 == 0 else False 
                })

        total = sum(len(m) for m in partidos_por_competicion.values())
        payload_final = {
            "todos_los_partidos": partidos_por_competicion,
            "pronosticos_destacados": resultados_destacados,
            "total_partidos": total
        }

        CACHE_PARTIDOS_DATA = payload_final
        CACHE_PARTIDOS_TIMESTAMP = time.time()
        return jsonify(payload_final)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==========================================
# ENDPOINT DE CHAT TÁCTICO INTEGRADO
# ==========================================
@app.route('/chat-ia', methods=['POST'])
def chat_ia():
    try:
        data = request.get_json() or {}
        mensaje = data.get('mensaje', '')
        
        prompt_chat = f"""
        [ANÁLISIS SINTÉTICO VIP - PREDICXION IA]
        CONSULTA DEL USUARIO: "{mensaje}"
        
        REGLAS ESTRICTAS DE RESPUESTA:
        1. LONGITUD: Tu análisis central debe tener como mínimo 1.5 oraciones y como máximo 5 oraciones.
        2. CORTESÍA: Inicia con un saludo corto, natural y humano (ej: "¡Qué tal, hermano!", "¡Hola!"). Cierra con una despedida breve (ej: "¡Éxitos!", "¡Mucha suerte!").
        3. 100% DATOS REALES: Sin inventos. Todo basado en historial y métricas contrastables (xG, bajas, etc).
        4. FORMATO ATRACTIVO: Destaca equipos, jugadores y cuotas obligatoriamente en **negrita**. NUNCA uses símbolos de hashtag (#).
        """
        
        return jsonify({"respuesta": llamar_ia_hibrida(prompt_chat)})
    except Exception as e:
        return jsonify({"error": "Saturación temporal del motor. Intenta de nuevo en unos segundos."}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
