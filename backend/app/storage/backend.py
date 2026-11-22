"""StorageBackend interface. LocalDiskStorage now; S3/MinIO later (config change)."""
import hashlib
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import get_settings


class StorageBackend(ABC):
    @abstractmethod
    def put(self, data: bytes, prefix: str = "originals", ext: str = "bin") -> str: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...


class LocalDiskStorage(StorageBackend):
    """Random object keys, stored outside any web root; never served by path."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("invalid storage key")
        return p

    def put(self, data: bytes, prefix: str = "originals", ext: str = "bin") -> str:
        key = f"{prefix}/{uuid.uuid4().hex}.{ext}"
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_storage: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _storage
    if _storage is None:
        s = get_settings()
        if s.storage_backend != "local":
            raise NotImplementedError("S3/MinIO backend is a future drop-in implementation")
        _storage = LocalDiskStorage(s.storage_root)
    return _storage
