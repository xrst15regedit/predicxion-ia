import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any
from .station_topology import GlobalTopologyManager, RegionZone, StationNode
from .predictive_engine import FullTenDimensionsAnalyzer

class MultiRegionScheduler:
    """Planificador con activación programada a las 02:30 AM hora local por región."""

    def __init__(self, analyzer: FullTenDimensionsAnalyzer):
        self.analyzer = analyzer
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self._running = False

    @staticmethod
    def get_zone_offset(zone: RegionZone) -> int:
        mapping = {
            RegionZone.UTC_MINUS_5: -5,
            RegionZone.UTC_ZERO: 0,
            RegionZone.UTC_PLUS_3: 3,
            RegionZone.UTC_PLUS_8: 8
        }
        return mapping[zone]

    def seconds_until_target(self, zone: RegionZone, target_hour: int = 2, target_minute: int = 30) -> float:
        offset = self.get_zone_offset(zone)
        tz = timezone(timedelta(hours=offset))
        now = datetime.now(tz)
        target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    async def execute_regional_cycle(self, node: StationNode) -> Dict[str, Any]:
        now_utc = datetime.utcnow()
        return {
            "node": node.station_id,
            "zone": node.zone.value,
            "timestamp": now_utc.isoformat(),
            "matches_analyzed": 0,
            "status": "COMPLETED"
        }

    async def start(self) -> None:
        self._running = True
        for zone, node in GlobalTopologyManager.NODES.items():
            self.active_tasks[node.station_id] = asyncio.create_task(self._zone_loop(node))

    async def _zone_loop(self, node: StationNode) -> None:
        while self._running:
            delay = self.seconds_until_target(node.zone, node.target_hour, node.target_minute)
            await asyncio.sleep(min(delay, 3600.0))
            if self.seconds_until_target(node.zone, node.target_hour, node.target_minute) <= 1.5:
                await self.execute_regional_cycle(node)
                await asyncio.sleep(120.0)

    def stop(self) -> None:
        self._running = False
        for task in self.active_tasks.values():
            task.cancel()
