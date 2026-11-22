"""External registry connector interface (STUB).

No live government integration is permitted without formal authorisation and approved
interfaces (PDF 2.2). This stub simulates outcomes so the UNAVAILABLE path can be shown.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.enums import Status


@dataclass
class RegistryResult:
    status: Status
    message: str
    source: str
    response_ref: str | None
    freshness: str | None
    attempts: int


class RegistryConnector(ABC):
    @abstractmethod
    def check(self, passport_number: str | None, issuer: str | None, simulate: str | None = None) -> RegistryResult: ...


class SimulatedRegistryConnector(RegistryConnector):
    name = "SIMULATED-REGISTRY (demo stub - not a real system)"

    def check(self, passport_number, issuer, simulate=None) -> RegistryResult:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if not passport_number:
            return RegistryResult(Status.INCONCLUSIVE, "No readable passport number to query.", self.name, None, None, 0)
        if simulate == "unavailable":
            return RegistryResult(Status.UNAVAILABLE,
                                  "The registry service did not respond (simulated timeout after 3 bounded retries). "
                                  "This is NOT a finding against the document. Retry later or follow the approved manual procedure.",
                                  self.name, None, None, 3)
        return RegistryResult(Status.PASS, "No lost/stolen/revoked record in the simulated registry.", self.name,
                              "SIM-" + __import__("hashlib").sha1(passport_number.encode()).hexdigest()[:8].upper(), f"queried {now}", 1)


def get_registry() -> RegistryConnector:
    return SimulatedRegistryConnector()
