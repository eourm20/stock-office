"""DEMO fixture provider. Synthetic, clearly-labelled data for deterministic tests only.

Fixture values are NOT real market data and must never be reported as such.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from stock_office.domain.models import Instrument, MarketSnapshot

from .base import ProviderResult, payload_hash, utcnow

DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures"


class FixtureProvider:
    name = "demo-fixture"

    def __init__(self, fixture_dir: Path = DEFAULT_FIXTURE_DIR) -> None:
        self.fixture_dir = fixture_dir

    def _path(self, instrument: Instrument) -> Path:
        return self.fixture_dir / f"{instrument.id.replace(':', '_')}.json"

    def supports(self, instrument: Instrument) -> bool:
        return self._path(instrument).exists()

    def fetch(self, instrument: Instrument, as_of: datetime) -> ProviderResult:
        if not self.supports(instrument):
            return ProviderResult(coverage_gaps=[f"{self.name}: no fixture for {instrument.id}"])
        doc = json.loads(self._path(instrument).read_text(encoding="utf-8"))
        if doc.get("demo") is not True:
            raise ValueError(f"fixture {self._path(instrument).name} must be labelled demo=true")
        ingested = utcnow()
        snapshots = [
            MarketSnapshot(
                id=f"demo-{instrument.symbol}-{i}",
                instrument_id=instrument.id,
                source=self.name,
                kind=item["kind"],
                observed_at=item["observed_at"],
                available_at=item["available_at"],
                ingested_at=ingested,
                currency=item.get("currency"),
                payload=item["payload"],
                payload_hash=payload_hash(item["payload"]),
                demo=True,
            )
            for i, item in enumerate(doc["snapshots"])
        ]
        return ProviderResult(snapshots=snapshots, coverage_gaps=list(doc.get("coverage_gaps", [])))
