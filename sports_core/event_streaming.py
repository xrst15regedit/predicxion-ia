from collections import deque
from typing import Dict, Any, List, Callable, Optional
from dataclasses import dataclass

@dataclass
class TelemetryEvent:
    timestamp_ms: int
    match_id: str
    event_type: str
    team_id: str
    coordinates: Optional[Dict[str, float]]
    payload: Dict[str, Any]

class RealTimeEventProcessor:
    """Motor de procesamiento de eventos en ventanas deslizantes (Complex Event Processing)."""

    def __init__(self, window_size_sec: int = 900):
        self.window_size_ms = window_size_sec * 1000
        self.windows: Dict[str, deque] = {}
        self.alert_subscribers: List[Callable[[Dict[str, Any]], None]] = []

    def ingest_event(self, event: TelemetryEvent) -> None:
        if event.match_id not in self.windows:
            self.windows[event.match_id] = deque()

        queue = self.windows[event.match_id]
        queue.append(event)

        threshold = event.timestamp_ms - self.window_size_ms
        while queue and queue[0].timestamp_ms < threshold:
            queue.popleft()

        self._evaluate_complex_rules(event.match_id, queue)

    def subscribe_alerts(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self.alert_subscribers.append(callback)

    def _evaluate_complex_rules(self, match_id: str, events: deque) -> None:
        recent_events = list(events)[-5:]
        if len(recent_events) >= 2:
            prev = recent_events[-2]
            curr = recent_events[-1]
            if prev.event_type == "TURNOVER_FORCED" and curr.event_type == "BOX_ENTRY":
                alert = {
                    "alert_id": f"ALERT-HIGH-THREAT-{match_id}-{curr.timestamp_ms}",
                    "match_id": match_id,
                    "type": "TACTICAL_RAPID_COUNTER",
                    "severity": "CRITICAL",
                    "timestamp": curr.timestamp_ms
                }
                for sub in self.alert_subscribers:
                    sub(alert)
