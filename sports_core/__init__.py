"""
Módulo de Automatización de Inteligencia Deportiva Multirregional
PredicXion IA Platform
"""

from .architecture import SystemConfig, MessageBrokerRouter
from .station_topology import GlobalTopologyManager, RegionZone, StationNode
from .data_ingestion import DataValidationPipeline, RawMatchFeed, EnvironmentalTelemetry
from .predictive_engine import FullTenDimensionsAnalyzer, MatchDimensionsResult
from .event_streaming import RealTimeEventProcessor, TelemetryEvent
from .distributed_scheduler import MultiRegionScheduler
from .security import SecurityGateway, require_intel_role
from .disaster_recovery import RegionFailoverCoordinator

__all__ = [
    "SystemConfig",
    "MessageBrokerRouter",
    "GlobalTopologyManager",
    "RegionZone",
    "StationNode",
    "DataValidationPipeline",
    "RawMatchFeed",
    "EnvironmentalTelemetry",
    "FullTenDimensionsAnalyzer",
    "MatchDimensionsResult",
    "RealTimeEventProcessor",
    "TelemetryEvent",
    "MultiRegionScheduler",
    "SecurityGateway",
    "require_intel_role",
    "RegionFailoverCoordinator",
]
