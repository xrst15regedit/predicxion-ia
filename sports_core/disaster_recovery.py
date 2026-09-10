import logging
from typing import Dict
from .station_topology import GlobalTopologyManager, StationNode

logger = logging.getLogger("DisasterRecovery")

class RegionFailoverCoordinator:
    """Gestor de contingencia regional activa con RTO <= 30s y RPO <= 5s."""

    def __init__(self):
        self.circuit_open: Dict[str, bool] = {
            node.station_id: False for node in GlobalTopologyManager.NODES.values()
        }
        self.active_dc: Dict[str, str] = {
            node.station_id: node.primary_datacenter for node in GlobalTopologyManager.NODES.values()
        }

    def evaluate_node_health(self, node: StationNode, current_latency_ms: float, errors_in_window: int) -> None:
        if current_latency_ms > node.max_tolerance_latency_ms or errors_in_window >= 5:
            if not self.circuit_open[node.station_id]:
                self.trigger_failover(node, reason=f"Latencia {current_latency_ms}ms / Errores {errors_in_window}")

    def trigger_failover(self, node: StationNode, reason: str) -> None:
        self.circuit_open[node.station_id] = True
        self.active_dc[node.station_id] = node.backup_datacenter
        logger.critical(
            f"[CRITICAL FAILOVER] Estación {node.station_id} conmutada a datacenter secundario: "
            f"{node.backup_datacenter}. Causa: {reason}."
        )

    def recover_node(self, node: StationNode) -> None:
        self.active_dc[node.station_id] = node.primary_datacenter
        self.circuit_open[node.station_id] = False
        logger.info(f"[NODE RESTORED] Estación {node.station_id} restablecida al datacenter primario.")
