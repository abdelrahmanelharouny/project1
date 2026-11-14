"""Pure deployment configuration tests; no remote API/database operations."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
spec = spec_from_file_location("deploy_database", ROOT / "deployment/scripts/database.py")
database = module_from_spec(spec)
spec.loader.exec_module(database)


class DeploymentGuardrails(unittest.TestCase):
    def test_disposable_requires_loopback_and_prefix(self):
        self.assertTrue(database.is_disposable(SimpleNamespace(host="127.0.0.1", database="croptwist_deploy_ci")))
        self.assertFalse(database.is_disposable(SimpleNamespace(host="db.supabase.co", database="croptwist_deploy_ci")))
        self.assertFalse(database.is_disposable(SimpleNamespace(host="localhost", database="postgres")))

    def test_target_fingerprint_contains_no_password(self):
        target = SimpleNamespace(host="example.invalid", port=5432, database="postgres", username="app", password="secret")
        digest = database.target_id(target)
        self.assertEqual(len(digest), 64)
        target.password = "changed-secret"
        self.assertEqual(digest, database.target_id(target))
        target.database = "different"
        self.assertNotEqual(digest, database.target_id(target))

    def test_every_git_deployment_is_off(self):
        config = json.loads((ROOT / "vercel.json").read_text())
        self.assertEqual(config["git"]["deploymentEnabled"], {"*": False})
        self.assertEqual(config["framework"], "nextjs")

    def test_migration_wrapper_has_no_reset_or_downgrade_command(self):
        source = (ROOT / "deployment/scripts/database.py").read_text()
        self.assertIn('choices=["plan", "probe", "upgrade"]', source)
        self.assertNotIn("command.downgrade(", source)
        self.assertNotIn("command.stamp(", source)
        self.assertIn("--owner-approved", source)
        self.assertIn("--approved-plan-sha256", source)

    def test_browser_source_does_not_use_port_query_or_api_origin(self):
        for name in ["api.ts", "api-p07.ts", "api-p3-account.ts", "api-p3-commercial.ts", "types.ts"]:
            source = (ROOT / "src/lib" / name).read_text()
            self.assertNotIn("XTransformPort", source)
            self.assertNotIn("CROPTWIST_API_ORIGIN", source)

    def test_workflow_has_no_provider_deployment(self):
        source = (ROOT / ".github/workflows/deployment-checks.yml").read_text()
        self.assertNotIn("secrets.", source)
        self.assertNotIn("vercel --prod", source)
        self.assertNotIn("supabase db push", source)
        self.assertNotIn("continue-on-error", source)
        self.assertIn("alembic check", source)

    def test_next_builder_and_runner_use_node(self):
        source = (ROOT / "Dockerfile").read_text()
        self.assertIn("FROM node:22-bookworm-slim AS builder", source)
        self.assertIn("FROM node:22-bookworm-slim AS runner", source)
        self.assertIn('CMD ["node", "server.js"]', source)
        config = json.loads((ROOT / "package.json").read_text())
        self.assertEqual(config["engines"]["node"], "22.x")
        self.assertIn("node node_modules/next/dist/bin/next build", config["scripts"]["build"])

    def test_isolated_standalone_packaging(self):
        import os
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / ".next-fixture/static").mkdir(parents=True)
            (base / ".next-fixture/standalone").mkdir()
            (base / "public").mkdir()
            (base / ".next-fixture/static/chunk.js").write_text("fixture")
            (base / "public/fixture.txt").write_text("fixture")
            result = subprocess.run(["node", str(ROOT / "scripts/package-standalone.mjs")],
                cwd=base, env={**os.environ, "NEXT_DIST_DIR": ".next-fixture"},
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((base / ".next-fixture/standalone/.next-fixture/static/chunk.js").is_file())
            self.assertTrue((base / ".next-fixture/standalone/public/fixture.txt").is_file())


if __name__ == "__main__":
    unittest.main()
