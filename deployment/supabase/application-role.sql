-- OWNER-REVIEWED MANUAL TEMPLATE; never executed against Supabase by this task.
-- Apply only to a fresh CropTwist-specific project AFTER migrations and inventory
-- review. Disable Data API first. Replace postgres default-owner reference if
-- migration objects belong to another role. No passwords are embedded here.
-- CREATE ROLE intentionally stops on conflict; it never alters an existing role.
BEGIN;
CREATE ROLE croptwist_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
GRANT CONNECT ON DATABASE postgres TO croptwist_app;
GRANT USAGE ON SCHEMA public, extensions TO croptwist_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO croptwist_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO croptwist_app;
GRANT SELECT ON extensions.spatial_ref_sys TO croptwist_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO croptwist_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO croptwist_app;
ALTER ROLE croptwist_app SET search_path = public, extensions;
COMMIT;
-- Set its password using a protected dashboard/operator flow, or psql's
-- interactive \password croptwist_app, not a SQL literal in repository/logs.
-- Verify: application DML/spatial/readiness works; CREATE/ALTER/DROP fails.
-- Do not grant privileges on Supabase auth/storage schemas or administrator
-- membership. Verify function/type EXECUTE/USAGE if platform defaults changed.
