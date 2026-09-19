import logging
import os
from datetime import datetime, timedelta

import firebase_admin
import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from firebase_admin import credentials, firestore
from pytz import timezone
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("etl_pipeline.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


if not firebase_admin._apps:
    firebase_credentials_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
    if not firebase_credentials_path or not os.path.isfile(firebase_credentials_path):
        raise RuntimeError(
            "FIREBASE_CREDENTIALS_PATH debe apuntar a una credencial de Firebase válida fuera del repositorio."
        )
    firebase_admin.initialize_app(credentials.Certificate(firebase_credentials_path))
db = firestore.client()


class ETLPipeline:
    """Sincroniza el calendario oficial de Football-Data.org con Firestore."""

    def __init__(self):
        self.api_url = os.getenv("FOOTBALL_API_URL", "https://api.football-data.org/v4/matches")
        self.api_key = os.getenv("FOOTBALL_API_KEY") or os.getenv("API_KEY_FUTBOL")
        self.session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    @staticmethod
    def date_window() -> tuple[str, str]:
        try:
            lookahead = max(1, min(int(os.getenv("CALENDAR_LOOKAHEAD_DAYS", "45")), 90))
            backfill = max(0, min(int(os.getenv("CALENDAR_BACKFILL_DAYS", "7")), 30))
        except ValueError as exc:
            raise ValueError("Las ventanas del calendario deben ser enteros.") from exc
        now = datetime.utcnow()
        return (
            (now - timedelta(days=backfill)).date().isoformat(),
            (now + timedelta(days=lookahead)).date().isoformat(),
        )

    def extract(self) -> list[dict]:
        """Extrae solo encuentros devueltos por Football-Data.org en la ventana configurada."""
        if not self.api_key:
            raise RuntimeError("FOOTBALL_API_KEY no está configurada.")

        date_from, date_to = self.date_window()
        response = self.session.get(
            self.api_url,
            headers={"X-Auth-Token": self.api_key},
            params={"dateFrom": date_from, "dateTo": date_to},
            timeout=(5, 20),
        )
        response.raise_for_status()
        matches = response.json().get("matches")
        if not isinstance(matches, list):
            raise ValueError("Football-Data.org no devolvió una lista de partidos.")
        logger.info("Football-Data.org devolvió %d partidos entre %s y %s.", len(matches), date_from, date_to)
        return matches

    @staticmethod
    def transform(raw_data: list[dict]) -> list[dict]:
        """Conserva los datos de fuente; no crea xG, cuotas, partidos ni pronósticos."""
        transformed = []
        fetched_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

        for item in raw_data:
            match_id = item.get("id")
            home = (item.get("homeTeam") or {}).get("name")
            away = (item.get("awayTeam") or {}).get("name")
            utc_date = item.get("utcDate")
            competition = item.get("competition") or {}
            competition_name = competition.get("name")
            if not all((match_id, home, away, utc_date, competition_name)):
                logger.warning("Se descarta un partido de Football-Data.org con campos obligatorios ausentes.")
                continue

            transformed.append(
                {
                    "id_partido": str(match_id),
                    "liga": competition_name,
                    "competicion": {
                        "id": competition.get("id"),
                        "code": competition.get("code"),
                        "name": competition_name,
                        "area": (competition.get("area") or {}).get("name"),
                    },
                    "local": home,
                    "visitante": away,
                    "fecha_utc": utc_date,
                    "estado": item.get("status", "SCHEDULED"),
                    "marcador": item.get("score") or {},
                    "calendar_status": "VERIFIED",
                    "source_data": {
                        "provider": "football-data.org/v4",
                        "endpoint": "/matches",
                        "fetched_at": fetched_at,
                        "last_updated": item.get("lastUpdated"),
                        "source_match_id": match_id,
                    },
                    "actualizado_en": firestore.SERVER_TIMESTAMP,
                }
            )
        return transformed

    @staticmethod
    def load(transformed_data: list[dict]) -> int:
        """Hace upsert en la colección que consume el calendario de la aplicación."""
        if not transformed_data:
            logger.info("Football-Data.org no devolvió partidos válidos para sincronizar.")
            return 0

        committed = 0
        batch = db.batch()
        for index, match in enumerate(transformed_data, start=1):
            document = db.collection("partidos_verificados").document(match["id_partido"])
            batch.set(document, match, merge=True)
            if index % 450 == 0:
                batch.commit()
                committed += 450
                batch = db.batch()
        if len(transformed_data) % 450:
            batch.commit()
        logger.info("Calendario actualizado: %d encuentros reales guardados.", len(transformed_data))
        return len(transformed_data)

    def run_pipeline(self) -> bool:
        logger.info("=== SINCRONIZACIÓN DE CALENDARIO INICIADA ===")
        try:
            self.load(self.transform(self.extract()))
            return True
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            logger.error("Sincronización de Football-Data.org fallida: %s", exc)
            return False


if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone=timezone("America/Lima"))
    etl = ETLPipeline()
    scheduler.add_job(etl.run_pipeline, "cron", hour=3, minute=0, id="football_data_calendar")
    logger.info("Sincronizador de Football-Data.org iniciado para las 03:00 America/Lima.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler detenido manualmente.")
