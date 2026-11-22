"""1:1 face verification interface (STUB for the first prototype).

Design constraints kept visible in code (PDF 5.5): 1:1 only (never 1:N search), gated on quality,
calibrated outcome categories (not an identity claim), human fallback. A licensed, independently
evaluated model plugs in behind this interface later.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.enums import Status


@dataclass
class FaceOutcome:
    quality_status: Status
    comparison_status: Status
    message: str
    model_version: str


class FaceVerifier(ABC):
    @abstractmethod
    def verify(self, document_portrait: bytes | None, live_capture: bytes | None) -> FaceOutcome: ...


class NotConfiguredFaceVerifier(FaceVerifier):
    version = "none (stub)"

    def verify(self, document_portrait, live_capture) -> FaceOutcome:
        if live_capture is None:
            return FaceOutcome(Status.NOT_APPLICABLE, Status.NOT_APPLICABLE,
                               "No live capture was presented and no licensed comparison model is configured in this demo. "
                               "Officer performs the person-to-document comparison manually.", self.version)
        return FaceOutcome(Status.UNAVAILABLE, Status.UNAVAILABLE,
                           "No licensed face-comparison model is configured. Use the manual comparison procedure.", self.version)


def get_verifier() -> FaceVerifier:
    return NotConfiguredFaceVerifier()
