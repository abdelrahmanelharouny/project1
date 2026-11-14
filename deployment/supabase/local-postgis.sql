-- Disposable local init only. The postgis image may preinstall the extension
-- in public through its template database. Fail rather than relocate/drop it.
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA extensions;
-- If preinstalled in public, local compatibility still works with this path;
-- dedicated-schema verification uses the separate disposable test cluster.
ALTER DATABASE croptwist_deploy_local SET search_path = public, extensions;
