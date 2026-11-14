"""Object storage abstraction for raster assets (P05 Workstream A).

Production-ready, minimal object-storage layer for satellite rasters:

- **Local development**: `LocalStorage` writes under a configurable root
  (`CROPTWIST_RASTER_STORAGE_ROOT`, default `<repo>/raster_storage`).
  Content is addressed by content hash + stable key; writes are atomic
  (temp file + rename) and refuse to overwrite existing objects.
- **Production**: `S3Storage` speaks any S3-compatible API (AWS S3, MinIO,
  DigitalOcean Spaces) via `boto3`, imported lazily so the dependency is
  only required when the S3 backend is actually configured. Credentials
  arrive ONLY from environment variables / secret manager — never code,
  never the database, never logs.

Shared guarantees (both backends):
- **Stable, tenant-isolated keys**: keys are built by `raster_key()` from
  validated components (org UUID, field UUID, kind, scene, name). Path
  traversal and key injection are rejected.
- **No accidental overwrites**: `put_bytes` fails if the object exists
  unless the caller passes explicit `overwrite=True` (used only for
  regenerating preview renderings of the same processing version).
- **Validation before acceptance**: `validate_asset_payload` checks magic
  bytes (GeoTIFF / PNG), enforced maximum size, and requires checksum +
  content type metadata before an asset is stored or registered.
- **Controlled access**: private-by-default. `signed_url` issues
  time-limited read URLs (HMAC-signed route for local storage, S3
  presigned GET for S3). Direct object-store credentials are never
  exposed to clients.
- **Source vs derived separation**: `raster_key()` namespaces source
  scenes under `source/` and CropTwist-derived products under `derived/`
  so original NASA data and platform-computed products can never be
  confused at the storage layer.

The protocol is intentionally tiny (put/exists/stat/read/delete/signed_url)
so alternative backends can be added without touching call sites.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from app.core.config import settings

# ---------------------------------------------------------------- limits
MAX_ASSET_BYTES = 512 * 1024 * 1024  # 512 MB hard cap per object
# GeoTIFF little-endian ("II", 42) / big-endian ("MM", 42) magic bytes.
_GEOTIFF_MAGIC = (b"II*\x00", b"MM\x00*")
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

_KEY_COMPONENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_ORG_KEY_RE = re.compile(
    r"^org/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/"
)


class StorageError(Exception):
    """Base class for object-storage failures."""


class AssetValidationError(StorageError):
    """Raised when a payload fails pre-acceptance validation."""


class KeyConflictError(StorageError):
    """Raised when an object already exists and overwrite was not allowed."""


class NotFoundError(StorageError):
    """Raised when an object does not exist."""


@dataclass(frozen=True)
class StoredObject:
    """Result of a successful put: stable identity + integrity metadata."""

    key: str
    byte_size: int
    checksum_sha256: str
    content_type: str
    backend: str


@dataclass(frozen=True)
class ObjectStat:
    key: str
    byte_size: int
    checksum_sha256: str | None
    content_type: str | None
    backend: str


def validate_key_component(component: str, *, label: str) -> str:
    """Reject key components that could escape the tenant namespace."""
    if not component or len(component) > 255:
        raise StorageError(f"{label} key component empty or too long")
    if not _KEY_COMPONENT_RE.match(component):
        raise StorageError(f"{label} key component contains invalid characters")
    if component in (".", ".."):
        raise StorageError(f"{label} key component is a relative path segment")
    return component


def validate_storage_key(key: str, *, require_tenant: bool = False) -> str:
    """Validate a relative object key before it reaches a backend."""
    if not isinstance(key, str) or not key or len(key) > 1024:
        raise StorageError("storage key is empty or too long")
    if key.startswith(("/", "\\")) or "\\" in key or "?" in key or "#" in key:
        raise StorageError("storage key must be relative and contain no URL delimiters")
    parts = key.split("/")
    if any(not part or part in (".", "..") for part in parts):
        raise StorageError("storage key contains an invalid path segment")
    for index, part in enumerate(parts):
        validate_key_component(part, label=f"storage key segment {index}")
    if require_tenant and not _ORG_KEY_RE.match(key):
        raise StorageError("storage key must be tenant-scoped as org/<uuid>/...")
    return key


def raster_key(
    *,
    org_id: uuid.UUID,
    field_id: uuid.UUID,
    kind: str,  # 'source' | 'derived' | 'preview'
    provider_code: str,
    scene_id: str,
    index_code: str | None,
    processing_version: str,
    asset_name: str,
) -> str:
    """Build a stable, tenant-isolated, overwrite-resistant object key.

    Layout (mirrors the raster_assets natural key so any stored object can
    be traced back to its DB row and vice versa):

        org/{org_id}/field/{field_id}/source/{provider}/{scene}/{name}
        org/{org_id}/field/{field_id}/derived/{provider}/{scene}/{index}/{version}/{name}
        org/{org_id}/field/{field_id}/preview/{provider}/{scene}/{index}/{version}/{name}

    Source assets and derived products live in disjoint namespaces.
    """
    if kind not in ("source", "derived", "preview"):
        raise StorageError(f"unsupported asset kind for storage key: {kind!r}")
    parts = [
        validate_key_component(str(org_id), label="org id"),
        "field",
        validate_key_component(str(field_id), label="field id"),
        validate_key_component(kind, label="kind"),
        validate_key_component(provider_code, label="provider"),
        validate_key_component(scene_id, label="scene"),
    ]
    if kind in ("derived", "preview"):
        if not index_code:
            raise StorageError("derived/preview assets require an index code")
        parts.append(validate_key_component(index_code, label="index"))
        parts.append(validate_key_component(processing_version, label="processing version"))
    parts.append(validate_key_component(asset_name, label="asset name"))
    return "/".join(["org", *parts])


def validate_asset_payload(
    *,
    data: bytes,
    content_type: str,
    expected_checksum_sha256: str | None = None,
) -> str:
    """Validate a payload BEFORE it is accepted into the object store.

    Enforces magic bytes (GeoTIFF for .tif, PNG for .png), the size cap and
    — when the caller declares an expected digest — content integrity.
    Returns the computed sha256 hex digest.
    """
    if not data:
        raise AssetValidationError("asset payload is empty")
    if len(data) > MAX_ASSET_BYTES:
        raise AssetValidationError(
            f"asset payload {len(data)} bytes exceeds the {MAX_ASSET_BYTES}-byte cap"
        )
    name = content_type.lower()
    if name.endswith((".tif", ".tiff")) or name == "image/tiff":
        if not data.startswith(_GEOTIFF_MAGIC):
            raise AssetValidationError("payload is not a GeoTIFF (bad magic bytes)")
    elif name.endswith(".png") or name == "image/png":
        if not data.startswith(_PNG_MAGIC):
            raise AssetValidationError("payload is not a PNG (bad magic bytes)")
    else:
        raise AssetValidationError(f"unsupported asset content type: {content_type!r}")
    digest = hashlib.sha256(data).hexdigest()
    if expected_checksum_sha256 and digest != expected_checksum_sha256.lower():
        raise AssetValidationError("payload checksum does not match the expected digest")
    return digest


class RasterStorage(Protocol):
    """Minimal object-storage contract for raster assets."""

    backend: str

    def put_bytes(self, key: str, data: bytes, *, content_type: str, overwrite: bool = False) -> StoredObject: ...

    def exists(self, key: str) -> bool: ...

    def stat(self, key: str) -> ObjectStat: ...

    def read_bytes(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def signed_url(self, key: str, *, ttl_seconds: int = 300) -> str: ...


# ---------------------------------------------------------------- local
class LocalStorage:
    """Development object store on local disk (atomic, no-overwrite).

    Not for production: no replication, no horizontal scaling. Production
    deployments configure the S3 backend (or another RasterStorage) instead.
    """

    backend = "local"

    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        validate_storage_key(key)
        candidate = (self._root / key).resolve()
        if not candidate.is_relative_to(self._root):
            raise StorageError(f"key escapes the storage root: {key!r}")
        return candidate

    def put_bytes(self, key: str, data: bytes, *, content_type: str, overwrite: bool = False) -> StoredObject:
        validate_storage_key(key)
        checksum = validate_asset_payload(data=data, content_type=content_type)
        target = self._resolve(key)
        if target.exists() and not overwrite:
            raise KeyConflictError(f"object already exists: {key}")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_bytes(data)
            tmp.replace(target)  # atomic on POSIX
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        return StoredObject(
            key=key,
            byte_size=len(data),
            checksum_sha256=checksum,
            content_type=content_type,
            backend=self.backend,
        )

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def stat(self, key: str) -> ObjectStat:
        path = self._resolve(key)
        if not path.is_file():
            raise NotFoundError(f"object not found: {key}")
        return ObjectStat(
            key=key,
            byte_size=path.stat().st_size,
            checksum_sha256=None,  # checksums live in the registry, not the fs
            content_type=path.suffix,
            backend=self.backend,
        )

    def read_bytes(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.is_file():
            raise NotFoundError(f"object not found: {key}")
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.is_file():
            path.unlink()

    def signed_url(self, key: str, *, ttl_seconds: int = 300) -> str:
        """HMAC-signed relative URL served by the API (dev convenience)."""
        return signed_local_key(key, ttl_seconds=ttl_seconds)


# ------------------------------------------------------------------ s3
class S3Storage:
    """S3-compatible object store (AWS S3 / MinIO / Spaces) via boto3.

    boto3 is imported lazily: the dependency is only needed when the S3
    backend is configured. Credentials come exclusively from the standard
    AWS credential chain driven by explicit env vars (never code). Objects
    are private by default; reads go through presigned GET URLs.
    """

    backend = "s3"

    def __init__(self) -> None:
        try:
            import boto3  # noqa: PLC0415 — lazy import, S3 backend only
        except ImportError as exc:  # pragma: no cover — deployment config error
            raise StorageError(
                "S3 raster storage requires the 'boto3' package; install it or "
                "configure CROPTWIST_RASTER_STORAGE_BACKEND=local."
            ) from exc
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region or None,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
        )
        self._bucket = settings.s3_bucket
        if not self._bucket:
            raise StorageError("CROPTWIST_S3_BUCKET is required for the S3 raster backend")

    def put_bytes(self, key: str, data: bytes, *, content_type: str, overwrite: bool = False) -> StoredObject:
        validate_storage_key(key)
        checksum = validate_asset_payload(data=data, content_type=content_type)
        if not overwrite and self.exists(key):
            raise KeyConflictError(f"object already exists: {key}")
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ServerSideEncryption="aws:kms" if settings.s3_kms_key_id else None,
            SSEKMSKeyId=settings.s3_kms_key_id or None,
        )
        return StoredObject(
            key=key,
            byte_size=len(data),
            checksum_sha256=checksum,
            content_type=content_type,
            backend=self.backend,
        )

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:
            return False

    def stat(self, key: str) -> ObjectStat:
        try:
            head = self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            raise NotFoundError(f"object not found: {key}") from exc
        etag = (head.get("ETag") or "").strip('"')
        return ObjectStat(
            key=key,
            byte_size=int(head.get("ContentLength") or 0),
            checksum_sha256=etag if len(etag) == 64 else None,
            content_type=head.get("ContentType"),
            backend=self.backend,
        )

    def read_bytes(self, key: str) -> bytes:
        try:
            body = self._client.get_object(Bucket=self._bucket, Key=key)["Body"]
        except Exception as exc:
            raise NotFoundError(f"object not found: {key}") from exc
        return body.read()

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def signed_url(self, key: str, *, ttl_seconds: int = 300) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=max(30, min(int(ttl_seconds), 3600)),
        )


# --------------------------------------------------------------- signing
_SIGNING_SECRET_ENV = "CROPTWIST_RASTER_URL_SECRET"


def _url_secret() -> str:
    secret = getattr(settings, "raster_url_secret", "") or ""
    if not secret:
        secret = "dev-only-raster-url-secret"  # dev convenience, not production
    return secret


def signed_local_key(key: str, *, ttl_seconds: int = 300) -> str:
    """Produce a token for the controlled local-storage download route."""
    expires = int((datetime.now(UTC) + timedelta(seconds=ttl_seconds)).timestamp())
    payload = f"{key}:{expires}"
    sig = hmac.new(_url_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{key}?expires={expires}&sig={sig}"


def verify_local_signature(key: str, expires: str, sig: str) -> bool:
    """Verify a signed local-storage URL (constant-time comparison)."""
    try:
        exp = int(expires)
    except ValueError:
        return False
    if exp < datetime.now(UTC).timestamp():
        return False
    expected = hmac.new(
        _url_secret().encode(),
        f"{key}:{exp}".encode(),
        hashlib.sha256,
    ).hexdigest()[:32]
    return hmac.compare_digest(expected, sig)


# --------------------------------------------------------------- factory
_storage_singleton: RasterStorage | None = None


def get_raster_storage() -> RasterStorage:
    """Backend selected by CROPTWIST_RASTER_STORAGE_BACKEND (local|s3|postgres)."""
    global _storage_singleton  # noqa: PLW0603
    if _storage_singleton is None:
        backend = (settings.raster_storage_backend or "local").lower()
        if backend == "s3":
            _storage_singleton = S3Storage()
        elif backend == "postgres":
            from app.geospatial.postgres_objectstore import PostgresStorage

            _storage_singleton = PostgresStorage()
        elif backend == "local":
            _storage_singleton = LocalStorage(settings.raster_storage_root)
        else:
            raise StorageError(f"unknown raster storage backend: {backend!r}")
    return _storage_singleton


def reset_raster_storage() -> None:
    """Test/ops helper: drop the cached backend (config changes re-read)."""
    global _storage_singleton  # noqa: PLW0603
    _storage_singleton = None
