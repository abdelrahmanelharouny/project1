"""Unit tests for the P05 object-storage abstraction.

Covers: upload/download/existence/deletion, overwrite protection, payload
validation (magic bytes, size cap, checksum), stable tenant-isolated keys,
path-traversal rejection, signed-URL verification, backend isolation, and
the source/derived namespace separation. S3 backend is exercised through a
fake boto3 client (no network, no credentials).
"""

from __future__ import annotations

import hashlib
import struct
import zlib

import pytest

from app.geospatial import objectstore as ost


def _png_bytes(size: int = 10) -> bytes:
    """Smallest valid PNG (1x1 grey) built by hand (IHDR/IDAT/IEND)."""
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    raw = b"\x00\x80"  # filter 0 + grey pixel
    idat = zlib.compress(raw)
    crc = lambda tag, payload: struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)  # noqa: E731
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + crc(b"IHDR", ihdr)
        + struct.pack(">I", len(idat)) + b"IDAT" + idat + crc(b"IDAT", idat)
        + struct.pack(">I", 0) + b"IEND" + crc(b"IEND", b"")
    )


def _tiff_bytes() -> bytes:
    # Minimal little-endian TIFF header (magic bytes are what matters here).
    return b"II*\x00" + b"\x00" * 32


class TestLocalStorageContract:
    def test_put_read_roundtrip(self, tmp_path):
        store = ost.LocalStorage(str(tmp_path))
        key = "org/00000000-0000-0000-0000-000000000001/field/00000000-0000-0000-0000-000000000002/derived/nasa_hls/S1/ndvi/v1/prod.tif"
        data = _tiff_bytes()
        stored = store.put_bytes(key, data, content_type="image/tiff")
        assert stored.key == key
        assert stored.checksum_sha256 == hashlib.sha256(data).hexdigest()
        assert stored.backend == "local"
        assert store.exists(key)
        assert store.read_bytes(key) == data
        assert store.stat(key).byte_size == len(data)

    def test_overwrite_refused_without_flag(self, tmp_path):
        store = ost.LocalStorage(str(tmp_path))
        key = "k/a/b.tif"
        store.put_bytes(key, _tiff_bytes(), content_type="image/tiff")
        with pytest.raises(ost.KeyConflictError):
            store.put_bytes(key, _tiff_bytes(), content_type="image/tiff")
        # explicit overwrite is allowed (deliberate regeneration only)
        store.put_bytes(key, _tiff_bytes(), content_type="image/tiff", overwrite=True)

    def test_delete_and_missing(self, tmp_path):
        store = ost.LocalStorage(str(tmp_path))
        store.put_bytes("x/y.tif", _tiff_bytes(), content_type="image/tiff")
        store.delete("x/y.tif")
        assert not store.exists("x/y.tif")
        with pytest.raises(ost.NotFoundError):
            store.read_bytes("x/y.tif")
        with pytest.raises(ost.NotFoundError):
            store.stat("x/y.tif")

    def test_path_traversal_rejected(self, tmp_path):
        store = ost.LocalStorage(str(tmp_path))
        with pytest.raises(ost.StorageError):
            store.read_bytes("../../etc/passwd")
        with pytest.raises(ost.StorageError):
            store.put_bytes("a/../../escape.tif", _tiff_bytes(), content_type="image/tiff")


class TestPayloadValidation:
    def test_geotiff_magic_enforced(self, tmp_path):
        store = ost.LocalStorage(str(tmp_path))
        with pytest.raises(ost.AssetValidationError):
            store.put_bytes("x.tif", b"NOTATIFF" * 4, content_type="image/tiff")

    def test_png_magic_enforced(self, tmp_path):
        store = ost.LocalStorage(str(tmp_path))
        with pytest.raises(ost.AssetValidationError):
            store.put_bytes("x.png", b"\x89PNG-corrupt", content_type="image/png")
        data = _png_bytes()
        stored = store.put_bytes("ok.png", data, content_type="image/png")
        assert stored.byte_size == len(data)

    def test_empty_and_oversize_rejected(self, tmp_path):
        store = ost.LocalStorage(str(tmp_path))
        with pytest.raises(ost.AssetValidationError):
            store.put_bytes("x.tif", b"", content_type="image/tiff")
        with pytest.raises(ost.AssetValidationError):
            ost.validate_asset_payload(data=b"z" * (ost.MAX_ASSET_BYTES + 1), content_type="image/tiff")

    def test_checksum_mismatch_rejected(self, tmp_path):
        store = ost.LocalStorage(str(tmp_path))
        data = _tiff_bytes()
        wrong = "0" * 64
        with pytest.raises(ost.AssetValidationError):
            ost.validate_asset_payload(data=data, content_type="image/tiff", expected_checksum_sha256=wrong)
        ok = ost.validate_asset_payload(data=data, content_type="image/tiff", expected_checksum_sha256=hashlib.sha256(data).hexdigest())
        assert ok == hashlib.sha256(data).hexdigest()

    def test_unknown_content_type_rejected(self, tmp_path):
        with pytest.raises(ost.AssetValidationError):
            ost.validate_asset_payload(data=b"whatever", content_type="application/json")


class TestKeySafety:
    def test_stable_key_layout_and_isolation(self):
        k1 = ost.raster_key(
            org_id=ost.uuid.UUID("00000000-0000-0000-0000-00000000000a"),
            field_id=ost.uuid.UUID("00000000-0000-0000-0000-00000000000b"),
            kind="derived",
            provider_code="nasa_hls",
            scene_id="HLS.S30.T36RTT.1",
            index_code="ndvi",
            processing_version="v1",
            asset_name="x.tif",
        )
        assert k1.startswith("org/00000000-0000-0000-0000-00000000000a/field/")
        assert "/derived/" in k1
        # a different org/field NEVER collides on the same key
        k2 = ost.raster_key(
            org_id=ost.uuid.UUID("00000000-0000-0000-0000-00000000000c"),
            field_id=ost.uuid.UUID("00000000-0000-0000-0000-00000000000b"),
            kind="derived",
            provider_code="nasa_hls",
            scene_id="HLS.S30.T36RTT.1",
            index_code="ndvi",
            processing_version="v1",
            asset_name="x.tif",
        )
        assert k1 != k2

    def test_source_and_derived_namespaces_disjoint(self):
        common = dict(
            org_id=ost.uuid.UUID("00000000-0000-0000-0000-00000000000a"),
            field_id=ost.uuid.UUID("00000000-0000-0000-0000-00000000000b"),
            provider_code="nasa_hls",
            scene_id="S1",
            index_code="ndvi",
            processing_version="v1",
            asset_name="x.tif",
        )
        source = ost.raster_key(kind="source", **common)
        derived = ost.raster_key(kind="derived", **common)
        assert "/source/" in source and "/derived/" in derived
        assert source != derived

    def test_injection_and_traversal_rejected(self):
        base = dict(
            org_id=ost.uuid.UUID("00000000-0000-0000-0000-00000000000a"),
            field_id=ost.uuid.UUID("00000000-0000-0000-0000-00000000000b"),
            provider_code="nasa_hls",
            scene_id="S1",
            index_code="ndvi",
            processing_version="v1",
            asset_name="x.tif",
        )
        for field in ("scene_id", "asset_name", "processing_version", "index_code"):
            for bad in ("../..", "a/b", "a b", "", ".", ".."):
                with pytest.raises(ost.StorageError):
                    ost.raster_key(kind="derived", **{**base, field: bad})

    def test_derived_requires_index(self):
        with pytest.raises(ost.StorageError):
            ost.raster_key(
                org_id=ost.uuid.UUID("00000000-0000-0000-0000-00000000000a"),
                field_id=ost.uuid.UUID("00000000-0000-0000-0000-00000000000b"),
                kind="derived",
                provider_code="nasa_hls",
                scene_id="S1",
                index_code=None,
                processing_version="v1",
                asset_name="x.tif",
            )


class TestSignedUrls:
    def test_local_sign_verify_roundtrip(self):
        token = ost.signed_local_key("a/b.tif", ttl_seconds=60)
        key, query = token.split("?")
        params = dict(p.split("=") for p in query.split("&"))
        assert ost.verify_local_signature(key, params["expires"], params["sig"])

    def test_tampered_signature_rejected(self):
        token = ost.signed_local_key("a/b.tif", ttl_seconds=60)
        key, query = token.split("?")
        params = dict(p.split("=") for p in query.split("&"))
        assert not ost.verify_local_signature(key, params["expires"], "f" * 32)

    def test_expired_signature_rejected(self):
        token = ost.signed_local_key("a/b.tif", ttl_seconds=-10)
        key, query = token.split("?")
        params = dict(p.split("=") for p in query.split("&"))
        assert not ost.verify_local_signature(key, params["expires"], params["sig"])


class TestS3BackendWithFakeClient:
    """S3 backend exercised via a fake boto3 client (no network)."""

    class _FakeS3Client:
        def __init__(self):
            self.objects: dict[str, bytes] = {}

        def put_object(self, Bucket, Key, Body, ContentType, ServerSideEncryption=None, SSEKMSKeyId=None):
            self.objects[Key] = Body

        def head_object(self, Bucket, Key):
            if Key not in self.objects:
                raise LookupError("no object")
            return {"ContentLength": len(self.objects[Key]), "ETag": '"an-etag-not-64-chars"'}

        def get_object(self, Bucket, Key):
            return {"Body": TestS3BackendWithFakeClient._FakeBody(self.objects[Key])}

        def delete_object(self, Bucket, Key):
            self.objects.pop(Key, None)

        def generate_presigned_url(self, operation, Params, ExpiresIn):
            return f"https://fake-bucket.s3/presigned/{Params['Key']}?ttl={ExpiresIn}"

    class _FakeBody:
        def __init__(self, data: bytes):
            self._data = data

        def read(self) -> bytes:
            return self._data

    class _FakeBody:
        def __init__(self, data: bytes):
            self._data = data

        def read(self) -> bytes:
            return self._data

    @pytest.fixture()
    def s3_store(self, monkeypatch):
        fake = self._FakeS3Client()
        monkeypatch.setattr(
            "app.core.config.settings.s3_bucket", "test-bucket", raising=False
        )
        monkeypatch.setattr("app.core.config.settings.s3_endpoint_url", "", raising=False)
        monkeypatch.setattr("app.core.config.settings.s3_region", "", raising=False)
        monkeypatch.setattr("app.core.config.settings.s3_access_key_id", "", raising=False)
        monkeypatch.setattr("app.core.config.settings.s3_secret_access_key", "", raising=False)
        monkeypatch.setattr("app.core.config.settings.s3_kms_key_id", "", raising=False)
        import sys, types

        fake_boto3 = types.ModuleType("boto3")
        fake_boto3.client = lambda *a, **kw: fake
        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        return ost.S3Storage(), fake

    def test_s3_roundtrip_and_presign(self, s3_store):
        store, fake = s3_store
        data = _tiff_bytes()
        store.put_bytes("a/b.tif", data, content_type="image/tiff")
        assert store.exists("a/b.tif")
        assert store.read_bytes("a/b.tif") == data
        url = store.signed_url("a/b.tif", ttl_seconds=120)
        assert url.startswith("https://fake-bucket.s3/presigned/a/b.tif")
        store.delete("a/b.tif")
        assert not store.exists("a/b.tif")

    def test_s3_no_overwrite(self, s3_store):
        store, _ = s3_store
        store.put_bytes("a/b.tif", _tiff_bytes(), content_type="image/tiff")
        with pytest.raises(ost.KeyConflictError):
            store.put_bytes("a/b.tif", _tiff_bytes(), content_type="image/tiff")

    def test_s3_validation_still_applies(self, s3_store):
        store, _ = s3_store
        with pytest.raises(ost.AssetValidationError):
            store.put_bytes("a/b.tif", b"junk", content_type="image/tiff")
