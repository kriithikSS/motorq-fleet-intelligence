"""
Chaos Module — injects bursty, out-of-order, and duplicate events.
Simulates shift-start bursts (3x load), network recovery floods,
and duplicate event delivery for deduplication testing.
"""

import asyncio
import random
import time
from typing import List


class BurstSimulator:
    """
    Simulates 3x burst events at shift start (06:00, 14:00, 22:00)
    and random network reconnection storms.
    """

    def __init__(self, base_rate: int = 100_000, burst_multiplier: int = 3, burst_duration_sec: int = 300):
        self.base_rate = base_rate
        self.burst_multiplier = burst_multiplier
        self.burst_duration_sec = burst_duration_sec
        self._in_burst = False
        self._burst_end = 0.0

    def current_rate(self) -> int:
        """Return the current events/sec rate."""
        now = time.monotonic()
        if self._in_burst and now < self._burst_end:
            return self.base_rate * self.burst_multiplier
        elif self._in_burst:
            self._in_burst = False
        return self.base_rate

    def trigger_burst(self) -> None:
        """Trigger a burst episode."""
        self._in_burst = True
        self._burst_end = time.monotonic() + self.burst_duration_sec
        print(f"[CHAOS] Burst triggered: {self.base_rate * self.burst_multiplier:,} events/sec "
              f"for {self.burst_duration_sec}s")

    async def run_scheduled_bursts(self) -> None:
        """Schedule bursts at 06:00, 14:00, 22:00 every day."""
        import datetime
        while True:
            now = datetime.datetime.now()
            shift_starts = [6, 14, 22]
            for hour in shift_starts:
                next_burst = now.replace(hour=hour, minute=0, second=0, microsecond=0)
                if next_burst <= now:
                    continue
                wait_sec = (next_burst - now).total_seconds()
                await asyncio.sleep(wait_sec)
                self.trigger_burst()
            await asyncio.sleep(60)


class OutOfOrderInjector:
    """
    Buffers a fraction of events and re-emits them with a random delay
    to simulate out-of-order delivery (common in MQTT/reconnection scenarios).
    """

    def __init__(self, ooo_fraction: float = 0.02, max_delay_sec: float = 30.0):
        self.ooo_fraction = ooo_fraction
        self.max_delay_sec = max_delay_sec
        self._delayed_buffer: List[tuple] = []  # (emit_at, event_json)

    def inject(self, event_json: str) -> List[str]:
        """
        Returns a list of events to emit now.
        Some events may be withheld and emitted later.
        """
        now = time.monotonic()
        # Release any delayed events that are now due
        ready = []
        still_delayed = []
        for emit_at, evt in self._delayed_buffer:
            if now >= emit_at:
                ready.append(evt)
            else:
                still_delayed.append((emit_at, evt))
        self._delayed_buffer = still_delayed

        # Maybe delay this event
        if random.random() < self.ooo_fraction:
            delay = random.uniform(1.0, self.max_delay_sec)
            self._delayed_buffer.append((now + delay, event_json))
        else:
            ready.append(event_json)

        return ready


class DuplicateInjector:
    """
    Randomly duplicates events to test idempotency in the ingestion service.
    """

    def __init__(self, duplicate_rate: float = 0.005):
        self.duplicate_rate = duplicate_rate

    def inject(self, event_json: str) -> List[str]:
        """Returns 1 or 2 copies of the event."""
        if random.random() < self.duplicate_rate:
            return [event_json, event_json]  # duplicate
        return [event_json]


class ChaosEngine:
    """
    Combines all chaos mechanisms into a single middleware layer.
    Wrap your event emitter with this for realistic chaos testing.
    """

    def __init__(
        self,
        burst_multiplier: int = 3,
        ooo_fraction: float = 0.02,
        duplicate_rate: float = 0.005,
    ):
        self.burst_sim = BurstSimulator(burst_multiplier=burst_multiplier)
        self.ooo = OutOfOrderInjector(ooo_fraction=ooo_fraction)
        self.dup = DuplicateInjector(duplicate_rate=duplicate_rate)
        self._stats = {"emitted": 0, "duplicated": 0, "delayed": 0}

    def process(self, event_json: str) -> List[str]:
        """Process a single event through the chaos pipeline."""
        # Apply out-of-order injection
        ooo_events = self.ooo.inject(event_json)

        # Apply duplicate injection
        result = []
        for evt in ooo_events:
            duped = self.dup.inject(evt)
            if len(duped) > 1:
                self._stats["duplicated"] += 1
            result.extend(duped)

        self._stats["emitted"] += len(result)
        return result

    def stats(self) -> dict:
        return dict(self._stats)


if __name__ == "__main__":
    engine = ChaosEngine()
    sample = '{"vin":"1HGCM82633A004352","ts":"2026-09-25T10:15:02.120Z","speed_kmh":64.2}'

    for i in range(1000):
        events = engine.process(sample)

    print(f"Chaos stats: {engine.stats()}")
    print("Duplicate rate:", engine.stats()["duplicated"] / engine.stats()["emitted"])
