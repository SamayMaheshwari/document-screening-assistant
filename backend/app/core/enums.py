from enum import Enum


class Status(str, Enum):
    """Statuses used everywhere (PDF 5.6). UNAVAILABLE/INCONCLUSIVE are never fraud signals."""
    PASS = "PASS"
    FAIL = "FAIL"
    REVIEW = "REVIEW"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CaseStatus(str, Enum):
    NEW = "NEW"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    RECAPTURE_REQUIRED = "RECAPTURE_REQUIRED"
    FAILED = "FAILED"
    REVIEWED = "REVIEWED"


class Role(str, Enum):
    OFFICER = "officer"
    ADMIN = "admin"
    AUDITOR = "auditor"
