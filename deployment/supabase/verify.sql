-- READ ONLY. Run using the intended API login and session-mode pooler.
BEGIN READ ONLY;
SHOW server_version;
SHOW search_path;
SHOW ssl;
SHOW max_connections;
SELECT current_user, current_database(), pg_database_size(current_database()) AS database_bytes;
SELECT extname, extversion, nspname AS extension_schema
FROM pg_extension JOIN pg_namespace ON pg_namespace.oid = extnamespace
WHERE extname = 'postgis';
SELECT name, default_version, installed_version
FROM pg_available_extensions WHERE name IN ('postgis', 'postgis_raster');
SELECT PostGIS_Full_Version();
SELECT ST_SRID(ST_GeomFromText('POINT(31 30)',4326)) AS srid,
       ST_IsValid(ST_GeomFromText('MULTIPOLYGON(((31 30,31.01 30,31.01 30.01,31 30.01,31 30)))',4326)) AS valid,
       ST_Area(ST_GeomFromText('POLYGON((31 30,31.01 30,31.01 30.01,31 30.01,31 30))',4326)::geography) > 0 AS geodesic_area;
SELECT ssl, version AS tls_version FROM pg_stat_ssl WHERE pid = pg_backend_pid();
-- Execute after reviewed migrations only; an empty new project has no version table.
SELECT version_num FROM public.alembic_version;
ROLLBACK;
