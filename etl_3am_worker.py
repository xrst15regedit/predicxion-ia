import os
import time
import logging
from datetime import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import firebase_admin
from firebase_admin import credentials, firestore
from apscheduler.schedulers.blocking import BlockingScheduler
from pytz import timezone

# Configuración de Logging Estructurado
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("etl_pipeline.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Configuración Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate(os.getenv("FIREBASE_CREDENTIALS_PATH", "firebase_key.json"))
    firebase_admin.initialize_app(cred)
db = firestore.client()

class ETLPipeline:
    def __init__(self):
        self.api_url = os.getenv("FOOTBALL_API_URL", "https://api.football-data.org/v4/matches")
        self.api_key = os.getenv("FOOTBALL_API_KEY", "TU_API_KEY")
        
        # Configurar reintentos exponenciales para la extracción
        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def extract(self):
        """Extrae los partidos programados para las próximas 72 horas."""
        logger.info("Iniciando Fase de Extracción...")
        headers = {"X-Auth-Token": self.api_key}
        # En producción, calcula las fechas dinámicamente para el filtro de 72h
        params = {"status": "SCHEDULED"} 
        
        try:
            response = self.session.get(self.api_url, headers=headers, params=params, timeout=15)
            response.raise_for_status()
            data = response.json().get("matches", [])
            logger.info(f"Extracción exitosa: {len(data)} registros obtenidos.")
            return data
        except requests.exceptions.RequestException as e:
            logger.error(f"Error crítico en extracción: {e}")
            return []

    def transform(self, raw_data):
        """Limpia, normaliza y valida los datos extraídos."""
        logger.info("Iniciando Fase de Transformación...")
        transformed_data = []
        metrics = {"validos": 0, "rechazados": 0}

        for item in raw_data:
            try:
                # Reglas de negocio y validación de tipos
                match_id = str(item.get("id"))
                home_team = item.get("homeTeam", {}).get("name")
                away_team = item.get("awayTeam", {}).get("name")
                utc_date = item.get("utcDate")

                if not all([match_id, home_team, away_team, utc_date]):
                    metrics["rechazados"] += 1
                    continue

                # Normalización de datos para Firestore
                clean_match = {
                    "id_partido": match_id,
                    "local": home_team.strip().upper(),
                    "visitante": away_team.strip().upper(),
                    "fecha_utc": utc_date,
                    "estado_analisis": "PENDIENTE",
                    "timestamp_etl": firestore.SERVER_TIMESTAMP
                }
                transformed_data.append(clean_match)
                metrics["validos"] += 1

            except Exception as e:
                logger.warning(f"Error transformando registro {item.get('id')}: {e}")
                metrics["rechazados"] += 1

        logger.info(f"Transformación completada. Válidos: {metrics['validos']}, Rechazados: {metrics['rechazados']}")
        return transformed_data

    def load(self, transformed_data):
        """Carga en Firestore usando Batch (Transaccional/Upsert)."""
        logger.info("Iniciando Fase de Carga...")
        if not transformed_data:
            logger.warning("No hay datos para cargar.")
            return

        batch = db.batch()
        hoy = datetime.now().strftime("%Y-%m-%d")
        
        # Procesar en lotes de 500 (límite de Firestore Batch)
        for i, match in enumerate(transformed_data):
            doc_ref = db.collection("investigaciones_diarias").document(hoy).collection("partidos").document(match["id_partido"])
            # merge=True funciona como un Upsert
            batch.set(doc_ref, match, merge=True)
            
            if (i + 1) % 500 == 0:
                batch.commit()
                logger.info(f"Batch intermedio de {i+1} registros commiteado.")
                batch = db.batch()
                
        batch.commit()
        logger.info(f"Carga exitosa. Total insertados/actualizados: {len(transformed_data)}")

    def run_pipeline(self):
        logger.info("=== INICIANDO PIPELINE ETL ===")
        raw_data = self.extract()
        clean_data = self.transform(raw_data)
        self.load(clean_data)
        logger.info("=== PIPELINE ETL FINALIZADO ===")

if __name__ == "__main__":
    # Ejecución programada usando APScheduler (Zona Horaria Perú)
    scheduler = BlockingScheduler(timezone=timezone("America/Lima"))
    etl = ETLPipeline()
    
    # Programar a las 03:00 AM todos los días
    scheduler.add_job(etl.run_pipeline, 'cron', hour=3, minute=0)
    
    logger.info("Scheduler iniciado. Esperando ejecución a las 03:00 AM (America/Lima)...")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler detenido manualmente.")
