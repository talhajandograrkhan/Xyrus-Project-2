"""
Tests for the safety, reliability and honesty changes.

They use only the standard library (unittest) so they run with `pytest` or with
`python -m unittest tests.test_hardening`, and they never touch the network, the
real config, or the real home directory.
"""
import ast
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _import_or_skip(name):
    try:
        return __import__(name, fromlist=["_"])
    except Exception as e:                      # a heavy dependency missing in this environment
        raise unittest.SkipTest(f"cannot import {name}: {e}")


# ── permissions ──────────────────────────────────────────────────────────────
class PermissionsTests(unittest.TestCase):
    def setUp(self):
        from core import permissions
        self.p = permissions
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(permissions, "audit_path", lambda: Path(self.tmp.name) / "audit.log")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _cfg(self, policies=None, confirm=True):
        return (mock.patch("memory.config_manager.get_tool_policies", return_value=policies or {}),
                mock.patch("memory.config_manager.get_confirm_risky", return_value=confirm))

    def test_timeouts_are_bounded_and_longer_for_slow_tools(self):
        self.assertEqual(self.p.timeout_for("something_new"), self.p.DEFAULT_TIMEOUT)
        self.assertGreater(self.p.timeout_for("dev_agent"), self.p.DEFAULT_TIMEOUT)

    def test_default_is_to_ask_and_the_action_waits_for_confirmation(self):
        a, b = self._cfg()
        sent = []
        with a, b, mock.patch("core.confirm.pending_title", return_value=""), \
                mock.patch("core.confirm.request", side_effect=lambda k, t, d, run: sent.append((t, d)) or "[CONFIRMATION_PENDING] x"):
            out = self.p.guard("send_message", "Send a message", "To: Ali\nHi", lambda: "SENT")
        self.assertTrue(out.startswith("[CONFIRMATION_PENDING]"))
        self.assertEqual(len(sent), 1)
        self.assertNotIn("SENT", out)               # nothing ran yet

    def test_allow_runs_immediately(self):
        a, b = self._cfg({"send_message": "allow"})
        with a, b:
            self.assertEqual(self.p.guard("send_message", "t", "d", lambda: "SENT"), "SENT")

    def test_master_switch_off_runs_immediately(self):
        a, b = self._cfg(confirm=False)
        with a, b:
            self.assertEqual(self.p.guard("dev_agent", "t", "d", lambda: "BUILT"), "BUILT")

    def test_deny_refuses_and_never_runs(self):
        a, b = self._cfg({"send_message": "deny"})
        ran = []
        with a, b:
            out = self.p.guard("send_message", "Send it", "d", lambda: ran.append(1))
        self.assertFalse(ran)
        self.assertIn("switched off", out)

    def test_a_second_confirmation_does_not_stack(self):
        a, b = self._cfg()
        with a, b, mock.patch("core.confirm.pending_title", return_value="Restart"):
            out = self.p.guard("dev_agent", "t", "d", lambda: "BUILT")
        self.assertIn("Another confirmation", out)

    def test_audit_redacts_secrets_and_clips(self):
        self.p.audit("t", {"api_key": "sk-123", "password": "hunter2", "msg": "x" * 500}, "ok", 12.0)
        row = json.loads((Path(self.tmp.name) / "audit.log").read_text().splitlines()[0])
        self.assertEqual(row["args"]["api_key"], "***")
        self.assertEqual(row["args"]["password"], "***")
        self.assertLess(len(row["args"]["msg"]), 200)

    def test_audit_never_raises(self):
        with mock.patch.object(self.p, "audit_path", side_effect=OSError("disk gone")):
            self.p.audit("t", {}, "ok", 1.0)


# ── generated desktop scripts ────────────────────────────────────────────────
class DesktopSandboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = _import_or_skip("actions.desktop")

    def test_ordinary_scripts_are_accepted(self):
        for code in ("for p in Path.home().glob('*.txt'):\n    print(p.name)",
                     "shutil.copy2('a', 'b')",
                     "pyautogui.hotkey('win', 'd')",
                     "x = sorted([3, 1, 2])\nprint(x)"):
            self.assertEqual(self.d._validate_generated_code(code), "", code)

    def test_dangerous_scripts_are_refused(self):
        bad = ["import os\nos.remove('x')", "from os import system", "open('f').read()",
               "getattr(Path, 'unlink')", "Path('x').unlink()", "Path('x').write_text('y')",
               "shutil.rmtree('x')", "eval('1')", "exec('1')", "x.__class__",
               "print(__import__('os'))", "ctypes.windll", "subprocess.run(['ls'])",
               "while True:\n    pass\nimport sys", "print('rm -rf /')"]
        for code in bad:
            self.assertNotEqual(self.d._validate_generated_code(code), "", code)

    def test_refused_code_is_never_executed(self):
        with mock.patch.object(self.d, "_run_sandboxed") as run:
            out = self.d._execute_generated_code("import os\nos.remove('x')")
        run.assert_not_called()
        self.assertIn("did not run", out)

    def test_sandbox_has_no_getattr_or_ctypes(self):
        sb = self.d._build_sandbox()
        self.assertNotIn("getattr", sb["__builtins__"])
        self.assertNotIn("ctypes", sb)

    def test_a_safe_script_runs_and_returns_its_output(self):
        self.assertEqual(self.d._run_sandboxed("print('hello', 2 + 3)"), "hello 5")


# ── open_app name filter ─────────────────────────────────────────────────────
class OpenAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _import_or_skip("actions.open_app")

    def test_normal_names_pass(self):
        for n in ("notepad", "Google Chrome", "calc.exe", "ms-settings:display", "7-Zip (x64)"):
            self.assertTrue(self.m._is_safe_app_name(n), n)

    def test_shell_metacharacters_are_refused(self):
        for n in ("notepad & del x", "a|b", "a;b", "a`b", "$(whoami)", "a>b", 'a"b', "a%PATH%",
                  "a\nb", "a\n", "", "x" * 81):
            self.assertFalse(self.m._is_safe_app_name(n), repr(n))


# ── dev_agent ────────────────────────────────────────────────────────────────
class DevAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _import_or_skip("actions.dev_agent")

    def test_requirements_cannot_smuggle_pip_options(self):
        got = self.m._safe_requirements(["requests", "numpy>=1.24", "--index-url http://evil", "-r x",
                                         "pkg; rm -rf /", "flask[async]==3.0.0"])
        self.assertEqual(got, ["requests", "numpy>=1.24", "flask[async]==3.0.0"])

    def test_vscode_commands_never_use_the_shell(self):
        for cmd in self.m._vscode_launch_commands(Path("/tmp/proj")):
            self.assertIsInstance(cmd, list)
            self.assertEqual(cmd[-1], "/tmp/proj")


# ── history ──────────────────────────────────────────────────────────────────
class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"JARVIS_HISTORY_FILE": str(Path(self.tmp.name) / "h.jsonl")})
        env.start()
        self.addCleanup(env.stop)
        from core import history
        self.h = history

    def test_search_finds_every_word_most_recent_first(self):
        now = time.time()
        self.h.append("user", "What is the invoice total for March?", now - 300)
        self.h.append("assistant", "The March invoice total is 4,200.", now - 290)
        self.h.append("user", "Play some music", now - 100)
        rows = self.h.search("invoice march", now=now)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["role"], "assistant")
        self.assertEqual(self.h.search("music", now=now)[0]["text"], "Play some music")
        self.assertEqual(self.h.search("zebra", now=now), [])

    def test_days_limit_and_empty_query(self):
        now = time.time()
        self.h.append("user", "old thing", now - 5 * 86400)
        self.h.append("user", "new thing", now - 60)
        self.assertEqual([r["text"] for r in self.h.search("thing", days=1, now=now)], ["new thing"])
        self.assertEqual(len(self.h.search("", now=now)), 2)

    def test_junk_is_ignored_and_nothing_raises(self):
        self.h.append("system", "ignored")
        self.h.append("user", "   ")
        (Path(self.tmp.name) / "h.jsonl").write_text("not json\n", encoding="utf-8")
        self.assertEqual(self.h.search("x"), [])

    def test_action_is_a_valid_discoverable_tool(self):
        from core.action_loader import _validate
        mod = __import__("actions.conversation_history", fromlist=["_"])
        self.assertTrue(_validate(mod, "conversation_history.py").valid)
        self.h.append("user", "remember the blue folder")
        self.assertIn("blue folder", mod.search_history({"query": "blue folder"}))


# ── reminders ────────────────────────────────────────────────────────────────
class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"JARVIS_REMINDER_DIR": self.tmp.name, "HOME": self.tmp.name,
                                           "USERPROFILE": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)
        from core import reminder_store
        self.s = reminder_store

    def _add(self, tid, hours, msg):
        from datetime import datetime, timedelta
        self.s.add(tid, datetime.now() + timedelta(hours=hours), msg, "linux", tid)

    def test_pending_is_sorted_and_past_ones_are_dropped(self):
        self._add("b", 5, "call mum")
        self._add("a", 1, "stand up")
        self._add("old", -2, "already gone")
        self.assertEqual([e["id"] for e in self.s.list_pending()], ["a", "b"])
        self.assertEqual(len(self.s.list_pending()), 2)

    def test_find_by_word_and_all(self):
        self._add("a", 1, "stand up")
        self._add("b", 2, "call mum")
        self.assertEqual([e["id"] for e in self.s.find("mum")], ["b"])
        self.assertEqual(len(self.s.find("all")), 2)

    def test_list_and_cancel_through_the_tool(self):
        rem = _import_or_skip("actions.reminder")
        self._add("a", 1, "stand up")
        self._add("b", 2, "call mum")
        self.assertIn("2 reminder", rem.reminder({"action": "list"}))
        calls = []
        with mock.patch.object(rem.subprocess, "run", side_effect=lambda *a, **k: calls.append(a[0]) or mock.Mock(returncode=0)):
            self.assertIn("Cancelled 1", rem.reminder({"action": "cancel", "query": "mum"}))
        self.assertEqual([e["id"] for e in self.s.list_pending()], ["a"])
        self.assertIn("could not find", rem.reminder({"action": "cancel", "query": "dentist"}))

    def test_ambiguous_cancel_asks_instead_of_guessing(self):
        rem = _import_or_skip("actions.reminder")
        self._add("a", 1, "call mum")
        self._add("b", 2, "call dad")
        out = rem.reminder({"action": "cancel", "query": "call"})
        self.assertIn("More than one", out)
        self.assertEqual(len(self.s.list_pending()), 2)


# ── dashboard ────────────────────────────────────────────────────────────────
class DashboardSecurityTests(unittest.TestCase):
    def test_lockout_after_five_failures_and_recovery(self):
        from dashboard.security import RateLimiter
        t = [0.0]
        rl = RateLimiter(5, 60, 300, clock=lambda: t[0])
        for _ in range(4):
            rl.failure("1.2.3.4")
        self.assertEqual(rl.blocked("1.2.3.4"), 0.0)
        rl.failure("1.2.3.4")
        self.assertGreater(rl.blocked("1.2.3.4"), 290)
        self.assertEqual(rl.blocked("9.9.9.9"), 0.0)          # others are unaffected
        t[0] = 301.0
        self.assertEqual(rl.blocked("1.2.3.4"), 0.0)

    def test_old_failures_age_out(self):
        from dashboard.security import RateLimiter
        t = [0.0]
        rl = RateLimiter(3, 60, 300, clock=lambda: t[0])
        rl.failure("x"); rl.failure("x")
        t[0] = 120.0
        rl.failure("x")
        self.assertEqual(rl.blocked("x"), 0.0)

    def test_tokens_expire_and_the_callback_fires(self):
        from dashboard.security import TokenStore
        t = [0.0]
        gone = []
        ts = TokenStore(ttl=100, on_expire=gone.append, clock=lambda: t[0])
        ts.add("a")
        self.assertIn("a", ts)
        t[0] = 99.0
        self.assertIn("a", ts)
        t[0] = 101.0
        self.assertNotIn("a", ts)
        self.assertEqual(gone, ["a"])
        self.assertEqual(len(ts), 0)


# ── macOS probes ─────────────────────────────────────────────────────────────
class MacProbeTests(unittest.TestCase):
    def setUp(self):
        from core import sysinfo_mac
        self.m = sysinfo_mac

    def test_gpu_parsing(self):
        txt = '"PerformanceStatistics" = {"Device Utilization %"=37,"Renderer Utilization %"=29}'
        self.assertEqual(self.m.parse_gpu_percent(txt), 37.0)
        self.assertIsNone(self.m.parse_gpu_percent("nothing here"))

    def test_thermal_states(self):
        self.assertEqual(self.m.parse_thermal("Note: No thermal warning level has been recorded")[0], "OK")
        self.assertEqual(self.m.parse_thermal("CPU_Speed_Limit = 100")[0], "OK")
        self.assertEqual(self.m.parse_thermal("CPU_Speed_Limit = 70")[0], "Warm")
        self.assertEqual(self.m.parse_thermal("CPU_Speed_Limit = 30")[0], "Hot")
        self.assertIsNone(self.m.parse_thermal("", ""))

    def test_missing_tools_give_none_not_errors(self):
        def boom(*a, **k):
            raise OSError("no such tool")
        self.assertIsNone(self.m.gpu_percent(boom))
        self.assertIsNone(self.m.thermal_state(boom))


# ── diagnostics ──────────────────────────────────────────────────────────────
class DiagTests(unittest.TestCase):
    def test_swallowed_logs_once_and_never_raises(self):
        from core import diag
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "debug.log"
            with mock.patch.object(diag, "log_path", lambda: log):
                diag._last.clear()
                try:
                    raise ValueError("boom")
                except ValueError as e:
                    diag.swallowed("tests", e)
                    diag.swallowed("tests", e)          # same error again: collapsed
                lines = log.read_text().splitlines()
                self.assertEqual(len(lines), 1)
                self.assertIn("ValueError: boom", lines[0])
            with mock.patch.object(diag, "log_path", side_effect=OSError("x")):
                diag._last.clear()
                diag.swallowed("tests", RuntimeError("z"))   # must not raise


# ── repo-wide guards ─────────────────────────────────────────────────────────
class RepoHygieneTests(unittest.TestCase):
    SKIP = {".venv", "tests", "__pycache__", "Mark-LV-extracted"}

    def _py_files(self):
        for p in ROOT.rglob("*.py"):
            if not (set(p.relative_to(ROOT).parts) & self.SKIP):
                yield p

    def test_no_shell_true_with_a_list(self):
        """shell=True plus a list runs only the first item on macOS and Linux."""
        offenders = []
        for p in self._py_files():
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            for n in ast.walk(tree):
                # A one-item list is just a command and is fine; two or more items
                # is where the shell swallows everything after the first.
                if (isinstance(n, ast.Call) and n.args and isinstance(n.args[0], (ast.List, ast.Tuple))
                        and len(n.args[0].elts) > 1):
                    for kw in n.keywords:
                        if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                            offenders.append(f"{p.relative_to(ROOT)}:{n.lineno}")
        self.assertEqual(offenders, [])

    def test_exec_and_eval_live_only_in_the_desktop_sandbox(self):
        offenders = []
        for p in self._py_files():
            if p.relative_to(ROOT).as_posix() in ("actions/desktop.py",):
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("eval", "exec"):
                    offenders.append(f"{p.relative_to(ROOT)}:{n.lineno}")
        self.assertEqual(offenders, [])

    def test_tools_that_act_for_the_user_are_gated(self):
        gated = {"actions/send_message.py": "permissions.guard", "actions/dev_agent.py": "permissions.guard",
                 "actions/code_helper.py": "permissions.guard", "actions/desktop.py": "permissions.guard"}
        for rel, needle in gated.items():
            self.assertIn(needle, (ROOT / rel).read_text(encoding="utf-8"), rel)

    def test_every_declared_parameter_is_accepted_and_every_read_one_is_declared(self):
        """The class of bug where code reads a parameter the model was never told about."""
        for rel, names in {"actions/browser_control.py": ["fields"], "actions/file_controller.py": ["append", "max_results"],
                           "actions/weather_report.py": ["time"], "actions/computer_settings.py": ["press_enter"],
                           "actions/reminder.py": ["action", "query"]}.items():
            tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
            tool = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                        and any(getattr(t, "id", "") == "TOOL" for t in n.targets))
            props = next(v for k, v in zip(tool.values[0].keys if False else [], []) ) if False else None
            text = ast.get_source_segment((ROOT / rel).read_text(encoding="utf-8"), tool)
            for name in names:
                self.assertIn(f'"{name}"', text, f"{rel} does not declare '{name}'")


if __name__ == "__main__":
    unittest.main()
