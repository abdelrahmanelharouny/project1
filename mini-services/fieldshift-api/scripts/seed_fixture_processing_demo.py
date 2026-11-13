"""Dev-only demo seeder: labeled fixture scenes through the REAL P05 pipeline.

Creates clearly-labeled synthetic raster scenes (provider_code='fixture_demo',
is_synthetic=true, metadata.demo_fixture=true) for one or more demo fields,
writes their small deterministic GeoTIFFs under db/demo_fixtures/, and
enqueues preprocessing through the same idempotent processing path used for
real NASA HLS scenes. Observations produced from these scenes carry
evidence_class=synthetic_test_data and is_synthetic=true, and every UI
surface labels them as fixtures.

This script is a DEVELOPMENT convenience for verifying the derived-product
UX without Earthdata credentials. It never touches nasa_hls scene identity.

Usage:
    .venv/bin/python scripts/seed_fixture_processing_demo.py [--field-id UUID] [--process]
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURE_DIR = ROOT / "db" / "demo_fixtures"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--field-id", type=uuid.UUID, default=None)
    parser.add_argument("--process", action="store_true", help="enqueue preprocessing too")
    args = parser.parse_args()

    from app.core.database import SessionLocal
    from app.db.models import Field
    from app.db.models_p2 import SatelliteScene
    import json

    from sqlalchemy import text as sql_text

    from app.data_platform.registry.seed_sources import seed_data_registry
    from tests.fixtures.raster_fixtures import field_local_utm_scene_params, write_fixture_scene

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as db:
        seed_data_registry(db)
        db.commit()

        if args.field_id:
            fields = [db.get(Field, args.field_id)]
            if fields[0] is None:
                raise SystemExit("field not found")
        else:
            fields = db.query(Field).order_by(Field.created_at).limit(3).all()
        if not fields:
            raise SystemExit("no fields found; seed the demo workspace first")

        now = datetime.now(UTC)
        created: list[str] = []
        for fi, field in enumerate(fields):
            variants = [
                (f"FIXTURE-{field.id.hex[:6]}-A", now - timedelta(days=20), False, False, 5.0),
                (f"FIXTURE-{field.id.hex[:6]}-B", now - timedelta(days=8), True, False, 42.0),
                (f"FIXTURE-{field.id.hex[:6]}-C", now - timedelta(days=2), False, True, 12.0),
            ]
            geo = json.loads(
                db.execute(
                    sql_text("SELECT ST_AsGeoJSON(boundary) FROM fields WHERE id = :fid"),
                    {"fid": str(field.id)},
                ).scalar_one()
            )
            params = field_local_utm_scene_params(geo)
            for si, (scene_id, acquired_at, cloud, nodata, cloud_pct) in enumerate(variants):
                exists = db.query(SatelliteScene).filter_by(
                    field_id=field.id, provider_code="fixture_demo", scene_id=scene_id
                ).first()
                if exists is not None:
                    continue
                assets = write_fixture_scene(
                    FIXTURE_DIR,
                    scene_id=scene_id,
                    with_cloud_block=cloud,
                    with_nodata_patch=nodata,
                    **params,
                )
                db.add(
                    SatelliteScene(
                        field_id=field.id,
                        provider_code="fixture_demo",
                        product_code="fixture_demo_raster",
                        scene_id=scene_id,
                        acquired_at=acquired_at,
                        cloud_cover_pct=cloud_pct,
                        spatial_resolution_m=30.0,
                        band_mapping={"red": "B04", "nir": "B05", "fmask": "fmask"},
                        asset_refs=dict(assets),
                        is_synthetic=True,
                        processing_version="v1",
                        metadata_json={
                            "demo_fixture": True,
                            "platform": "SYNTHETIC FIXTURE",
                            "note": "labeled synthetic raster fixture for pipeline demo",
                        },
                        acquisition_status="ready",
                        discovered_at=now,
                        acquisition_updated_at=now,
                    )
                )
                created.append(scene_id)
        db.commit()
        print(f"created scenes: {created or ['(none — already present)']}")

        if args.process and created:
            from app.data_platform.processing.service import create_processing_jobs

            for field in fields:
                scene_ids = [
                    s for s in created if s.startswith(f"FIXTURE-{field.id.hex[:6]}")
                ]
                if not scene_ids:
                    continue
                result = create_processing_jobs(
                    db,
                    field=field,
                    scene_ids=scene_ids,
                    indices=["ndvi", "evi", "ndmi", "ndwi", "bsi"],
                )
                print(
                    f"field {field.id}: queued={result['queued_scenes']} "
                    f"jobs={len(result['jobs'])} skipped={len(result['skipped'])}"
                )
                for job in result["jobs"]:
                    from app.data_platform.processing.service import execute_processing_job

                    execute_processing_job(uuid.UUID(job["job_id"]), None)
                    print(f"  processed {job['scene_id']} -> {job['job_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
