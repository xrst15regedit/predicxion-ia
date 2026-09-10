from enum import Enum
from dataclasses import dataclass
from typing import Dict

class RegionZone(Enum):
    UTC_MINUS_5 = "UTC-5"  # CONMEBOL / CONCACAF
    UTC_ZERO = "UTC+0"     # UEFA Oeste / Premier / LaLiga
    UTC_PLUS_3 = "UTC+3"   # UEFA Este / AFC Oeste
    UTC_PLUS_8 = "UTC+8"   # AFC Este / J-League / CSL

@dataclass(frozen=True)
class StationNode:
    station_id: str
    zone: RegionZone
    primary_datacenter: str
    backup_datacenter: str
    target_hour: int = 2
    target_minute: int = 30
    max_tolerance_latency_ms: float = 180.0

class GlobalTopologyManager:
    """Gestor centralizado de topología de estaciones y sincronización CRDT."""
    NODES: Dict[RegionZone, StationNode] = {
        RegionZone.UTC_MINUS_5: StationNode(
            station_id="STATION-AMER-01",
            zone=RegionZone.UTC_MINUS_5,
            primary_datacenter="sa-east-1",
            backup_datacenter="us-east-1"
        ),
        RegionZone.UTC_ZERO: StationNode(
            station_id="STATION-EURO-01",
            zone=RegionZone.UTC_ZERO,
            primary_datacenter="eu-west-1",
            backup_datacenter="eu-central-1"
        ),
        RegionZone.UTC_PLUS_3: StationNode(
            station_id="STATION-EAST-01",
            zone=RegionZone.UTC_PLUS_3,
            primary_datacenter="me-south-1",
            backup_datacenter="eu-central-2"
        ),
        RegionZone.UTC_PLUS_8: StationNode(
            station_id="STATION-APAC-01",
            zone=RegionZone.UTC_PLUS_8,
            primary_datacenter="ap-northeast-1",
            backup_datacenter="ap-southeast-1"
        ),
    }

    @classmethod
    def get_node_for_zone(cls, zone: RegionZone) -> StationNode:
        return cls.NODES[zone]
