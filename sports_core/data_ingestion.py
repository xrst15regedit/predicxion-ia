import math
from typing import Dict, Any, List
from dataclasses import dataclass
from datetime import datetime

@dataclass
class EnvironmentalTelemetry:
    altitude_m: float
    temperature_c: float
    relative_humidity_pct: float
    barometric_pressure_hpa: float
    pitch_condition_index: float

@dataclass
class RawMatchFeed:
    match_id: str
    competition_code: str
    home_team: str
    away_team: str
    scheduled_utc: datetime
    venue_city: str
    venue_altitude_m: float
    raw_stats: Dict[str, Any]
    lineups_payload: Dict[str, Any]

class DataValidationPipeline:
    """Validador y enriquecedor de datos físicos, meteorológicos y tácticos."""

    @staticmethod
    def calculate_modified_zscore(values: List[float], current: float) -> float:
        if len(values) < 3:
            return 0.0
        sorted_vals = sorted(values)
        mid = len(sorted_vals) // 2
        median = sorted_vals[mid] if len(sorted_vals) % 2 != 0 else (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0
        deviations = [abs(x - median) for x in sorted_vals]
        sorted_devs = sorted(deviations)
        mad = sorted_devs[mid] if len(sorted_devs) % 2 != 0 else (sorted_devs[mid - 1] + sorted_devs[mid]) / 2.0
        if mad == 0.0:
            return 0.0
        return 0.6745 * (current - median) / mad

    @classmethod
    def sanitize_and_enrich(cls, feed: RawMatchFeed) -> Dict[str, Any]:
        if feed.scheduled_utc < datetime(2020, 1, 1):
            raise ValueError(f"Marca temporal no válida para el match_id {feed.match_id}")

        altitude = max(0.0, float(feed.venue_altitude_m))
        standard_pressure = 1013.25 * math.exp(-0.00012 * altitude)

        telemetry = EnvironmentalTelemetry(
            altitude_m=altitude,
            temperature_c=float(feed.raw_stats.get("temperature", 20.0)),
            relative_humidity_pct=float(feed.raw_stats.get("humidity", 55.0)),
            barometric_pressure_hpa=round(standard_pressure, 2),
            pitch_condition_index=float(feed.raw_stats.get("pitch_score", 0.95))
        )

        return {
            "match_id": feed.match_id,
            "competition": feed.competition_code,
            "home_team": feed.home_team,
            "away_team": feed.away_team,
            "timestamp": feed.scheduled_utc.isoformat(),
            "telemetry": telemetry,
            "raw_metrics": feed.raw_stats,
            "lineups": feed.lineups_payload,
            "ingested_at": datetime.utcnow().isoformat()
        }
