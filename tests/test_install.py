"""安装器测试。全部使用临时目录，不触碰真实 ~/.zcode。"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "install.py"
_spec = importlib.util.spec_from_file_location("zcode_install", MODULE_PATH)
install = importlib.util.module_from_spec(_spec)
sys.modules["zcode_install"] = install
_spec.loader.exec_module(install)

ROLES = ["architect", "builder", "expert", "reviewer-fallback", "reviewer", "verifier"]
FAKE_KEY = "FAKE-API-KEY-FOR-TESTS-ONLY"


def template(role: str) -> str:
    return (
        "---\n"
        f'name: "{role}"\n'
        f'description: "中文说明 {role}"\n'
        'model: "{{MODEL_REF}}"\n'
        'thoughtLevel: "{{THOUGHT_LEVEL}}"\n'
        "---\n\n"
        "# Role\n\nDo the assigned work.\n"
    )


class Fixture:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.repo = base / "repo"
        self.home = base / "zcode"
        (self.repo / "agents").mkdir(parents=True)
        (self.repo / "global").mkdir(parents=True)
        (self.home / "v2").mkdir(parents=True)
        for role in ROLES:
            (self.repo / "agents" / f"{role}.md").write_text(template(role), encoding="utf-8")
        (self.repo / "global" / "AGENTS.md").write_text("# Global rules\n", encoding="utf-8")
        self.write_config(
            {
                "chatgpt": {
                    "name": "chatgpt",
                    "enabled": True,
                    "options": {"apiKey": FAKE_KEY},
                    "models": {"gpt-6-astra": {}, "gpt-5.6-luna": {}},
                },
                "kimi": {
                    "name": "kimi",
                    "options": {"apiKey": FAKE_KEY},
                    "models": {"k3": {}},
                },
            }
        )
        self.write_state({"builtInModelOverrides": {}, "disabledAgentIds": []})

    def cleanup(self) -> None:
        self.tmp.cleanup()

    def write_config(self, providers: dict) -> None:
        path = self.home / "v2" / "config.json"
        path.write_text(json.dumps({"provider": providers}, indent=2), encoding="utf-8")

    def write_state(self, state: dict) -> None:
        (self.home / "v2" / "agents-state.json").write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )

    def state(self) -> dict:
        return json.loads((self.home / "v2" / "agents-state.json").read_text(encoding="utf-8"))

    def plan(self, **kwargs):
        return install.build_plan(self.repo, self.home, **kwargs)

    def apply(self, **kwargs):
        plan = self.plan(**kwargs)
        backup = install.apply_plan(plan, self.home) if not plan.is_empty else None
        return plan, backup


class PlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture()
        self.addCleanup(self.fx.cleanup)

    def test_dry_run_creates_nothing(self):
        before = sorted(p.name for p in self.fx.home.rglob("*"))
        plan = self.fx.plan(global_instructions=True)
        self.assertTrue(plan.writes)
        self.assertFalse((self.fx.home / "agents").exists())
        self.assertEqual(before, sorted(p.name for p in self.fx.home.rglob("*")))

    def test_resolves_unique_models_and_levels(self):
        plan = self.fx.plan()
        self.assertIn("custom:chatgpt:gpt-6-astra", plan.routes_used["architect"]["model"])
        self.assertEqual("xhigh", plan.routes_used["architect"]["thoughtLevel"])
        self.assertIn("k3", plan.routes_used["reviewer"]["model"])
        self.assertEqual("max", plan.routes_used["Explore"]["thoughtLevel"])

    def test_no_placeholder_left_in_output(self):
        plan = self.fx.plan()
        for content in plan.writes.values():
            self.assertNotIn("{{", content)

    def test_ambiguous_model_refuses(self):
        config = json.loads((self.fx.home / "v2" / "config.json").read_text())
        config["provider"]["second"] = {
            "name": "second",
            "enabled": True,
            "models": {"gpt-6-astra": {}},
        }
        self.fx.write_config(config["provider"])
        with self.assertRaises(install.InstallError) as ctx:
            self.fx.plan()
        self.assertIn("多个 provider", str(ctx.exception))

    def test_missing_model_refuses(self):
        self.fx.write_config({"chatgpt": {"name": "chatgpt", "enabled": True, "models": {}}})
        with self.assertRaises(install.InstallError) as ctx:
            self.fx.plan()
        self.assertIn("没有已启用", str(ctx.exception))

    def test_routes_override_wins(self):
        routes = self.fx.repo / "routes.json"
        routes.write_text(
            json.dumps({"architect": {"model": "custom:manual:custom-model", "thoughtLevel": "low"}}),
            encoding="utf-8",
        )
        plan = self.fx.plan(routes_path=routes)
        self.assertEqual("custom:manual:custom-model", plan.routes_used["architect"]["model"])
        self.assertEqual("low", plan.routes_used["architect"]["thoughtLevel"])

    def test_disabled_role_refuses(self):
        self.fx.write_state({"disabledAgentIds": ["user:user:reviewer"]})
        with self.assertRaises(install.InstallError) as ctx:
            self.fx.plan()
        self.assertIn("停用", str(ctx.exception))


class GlobalInstructionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture()
        self.addCleanup(self.fx.cleanup)

    def test_merge_preserves_surrounding_content(self):
        target = self.fx.home / "AGENTS.md"
        target.write_text("# 我的规则\n\n保留这段。\n", encoding="utf-8")
        plan, _ = self.fx.apply(global_instructions=True)
        text = target.read_text(encoding="utf-8")
        self.assertIn("保留这段。", text)
        self.assertIn(install.BEGIN_MARK, text)
        self.assertIn("# Global rules", text)

    def test_merge_is_idempotent(self):
        self.fx.apply(global_instructions=True)
        first = (self.fx.home / "AGENTS.md").read_text(encoding="utf-8")
        plan = self.fx.plan(global_instructions=True)
        self.assertNotIn(self.fx.home / "AGENTS.md", plan.writes)
        self.assertEqual(first, (self.fx.home / "AGENTS.md").read_text(encoding="utf-8"))

    def test_partial_marker_refuses(self):
        (self.fx.home / "AGENTS.md").write_text(install.BEGIN_MARK + "\n", encoding="utf-8")
        with self.assertRaises(install.InstallError):
            self.fx.plan(global_instructions=True)

    def test_no_global_flag_leaves_file_alone(self):
        self.fx.apply()
        self.assertFalse((self.fx.home / "AGENTS.md").exists())


class WriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture()
        self.addCleanup(self.fx.cleanup)

    def test_refuses_overwrite_without_flag_and_writes_nothing(self):
        dest = self.fx.home / "agents" / "architect.md"
        dest.parent.mkdir(parents=True)
        dest.write_text("existing\n", encoding="utf-8")
        with self.assertRaises(install.InstallError) as ctx:
            self.fx.plan()
        self.assertIn("--replace-existing", str(ctx.exception))
        self.assertEqual("existing\n", dest.read_text(encoding="utf-8"))
        self.assertFalse((self.fx.home / "agents" / "builder.md").exists())

    def test_replace_existing_allows_overwrite(self):
        dest = self.fx.home / "agents" / "architect.md"
        dest.parent.mkdir(parents=True)
        dest.write_text("existing\n", encoding="utf-8")
        self.fx.apply(replace_existing=True)
        self.assertIn("custom:chatgpt:gpt-6-astra", dest.read_text(encoding="utf-8"))

    def test_applies_roles_and_builtin_overrides(self):
        plan, backup = self.fx.apply()
        self.assertIsNotNone(backup)
        for role in ROLES:
            self.assertTrue((self.fx.home / "agents" / f"{role}.md").is_file())
        state = self.fx.state()
        self.assertEqual(
            "custom:chatgpt:gpt-5.6-luna", state["builtInModelOverrides"]["Explore"]
        )
        self.assertEqual("max", state["builtInThoughtLevelOverrides"]["general-purpose"])

    def test_preserves_unknown_state_keys(self):
        self.fx.write_state(
            {
                "builtInModelOverrides": {"legacy": "keep-me"},
                "builtInThoughtLevelOverrides": {},
                "disabledAgentIds": [],
                "futureField": {"nested": [1, 2, 3]},
            }
        )
        self.fx.apply()
        state = self.fx.state()
        self.assertEqual("keep-me", state["builtInModelOverrides"]["legacy"])
        self.assertEqual({"nested": [1, 2, 3]}, state["futureField"])

    def test_backup_created_before_write(self):
        dest = self.fx.home / "agents" / "architect.md"
        dest.parent.mkdir(parents=True)
        dest.write_text("existing\n", encoding="utf-8")
        _, backup = self.fx.apply(replace_existing=True)
        self.assertTrue((backup / "agents" / "architect.md").is_file())
        self.assertEqual("existing\n", (backup / "agents" / "architect.md").read_text())

    def test_config_file_never_modified(self):
        path = self.fx.home / "v2" / "config.json"
        before = path.read_bytes()
        self.fx.apply(global_instructions=True)
        self.assertEqual(before, path.read_bytes())

    def test_second_apply_is_noop(self):
        self.fx.apply()
        plan = self.fx.plan()
        self.assertTrue(plan.is_empty)


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture()
        self.addCleanup(self.fx.cleanup)

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = install.main(["--zcode-home", str(self.fx.home), "--repo", str(self.fx.repo)] + argv)
        return code, out.getvalue(), err.getvalue()

    def test_list_models_hides_secrets(self):
        code, out, _ = self.run_cli(["--list-models"])
        self.assertEqual(0, code)
        self.assertIn("gpt-6-astra", out)
        self.assertNotIn(FAKE_KEY, out)

    def test_dry_run_cli_mentions_apply(self):
        code, out, _ = self.run_cli(["--list-models", "--apply"])
        self.assertEqual(0, code)
        code, out, _ = self.run_cli([])
        self.assertEqual(0, code)
        self.assertIn("--apply", out)
        self.assertFalse((self.fx.home / "agents").exists())

    def test_error_exit_code_on_missing_model(self):
        self.fx.write_config({"chatgpt": {"name": "chatgpt", "enabled": True, "models": {}}})
        code, _, err = self.run_cli([])
        self.assertEqual(2, code)
        self.assertIn("未写入任何文件", err)


if __name__ == "__main__":
    unittest.main()
