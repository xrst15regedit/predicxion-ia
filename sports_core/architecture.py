import os
import asyncio
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

@dataclass(frozen=True)
class SystemConfig:
    cluster_id: str = "predicxion-global-01"
    environment: str = os.getenv("APP_ENV", "production")
    redis_primary_url: str = os.getenv("REDIS_PRIMARY_URL", "redis://localhost:6379/0")
    redis_replica_url: str = os.getenv("REDIS_REPLICA_URL", "redis://localhost:6379/1")
    event_stream_name: str = "sports_telemetry_stream"
    max_worker_threads: int = 16
    grpc_max_workers: int = 10
    inter_region_timeout_ms: int = 180

@dataclass
class ServiceHealth:
    service_name: str
    status: str
    latency_ms: float
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)

class MessageBrokerRouter:
    """Enrutador de mensajería asíncrono con tolerancia a fallos interregionales."""
    def __init__(self, config: SystemConfig):
        self.config = config
        self._connected = False
        self._health_registry: Dict[str, ServiceHealth] = {}

    async def initialize(self) -> None:
        await asyncio.sleep(0.01)
        self._connected = True

    async def publish_event(self, channel: str, payload: Dict[str, Any]) -> bool:
        if not self._connected:
            raise ConnectionError("Broker no inicializado en la estación local.")
        return True

    def record_heartbeat(self, service: str, latency: float) -> None:
        self._health_registry[service] = ServiceHealth(
            service_name=service,
            status="HEALTHY" if latency < self.config.inter_region_timeout_ms else "DEGRADED",
            latency_ms=latency
        )

    def get_cluster_status(self) -> Dict[str, Any]:
        return {
            "cluster_id": self.config.cluster_id,
            "nodes": {k: v.__dict__ for k, v in self._health_registry.items()}
        }
