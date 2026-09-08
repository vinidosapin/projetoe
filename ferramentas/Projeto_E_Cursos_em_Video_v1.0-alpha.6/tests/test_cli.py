from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from projeto_e_video.cli import _compact_search_output, main


class CliTests(unittest.TestCase):
    def test_doctor_is_offline_and_exposes_fallback_state(self) -> None:
        stdout = io.StringIO()
        with patch(
            "projeto_e_video.cli.preflight_report",
            return_value={
                "schema_name": "projeto-e-video.preflight",
                "core_ready": True,
                "manual_browser_flow_ready": True,
            },
        ), redirect_stdout(stdout):
            code = main(["doctor"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["core_ready"])
        self.assertTrue(payload["manual_browser_flow_ready"])

    def test_demo_runs_end_to_end_without_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name) / "demo"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["demo", "--workspace", str(workspace)])
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["course_state"], "DEMONSTRACAO_FIXTURE")
            self.assertTrue(payload["validation"]["valid"])
            self.assertTrue((workspace / "course" / "COURSE.md").is_file())

    def test_create_rejects_nonempty_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name) / "workspace"
            workspace.mkdir()
            (workspace / "mine.txt").write_text("preserve", encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = main(
                    [
                        "create",
                        "--input",
                        "cálculo",
                        "--workspace",
                        str(workspace),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("deve estar vazio", stderr.getvalue())
            self.assertEqual((workspace / "mine.txt").read_text(encoding="utf-8"), "preserve")

    def test_create_is_transactional_when_planning_fails(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name) / "workspace"
            stderr = io.StringIO()
            with patch(
                "projeto_e_video.cli.create_plan",
                side_effect=ValueError("falha de planejamento simulada"),
            ), redirect_stderr(stderr):
                code = main(
                    [
                        "create",
                        "--input",
                        "probabilidade condicional",
                        "--workspace",
                        str(workspace),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("falha de planejamento simulada", stderr.getvalue())
            self.assertTrue(workspace.is_dir())
            self.assertEqual(list(workspace.iterdir()), [])

    def test_create_commits_complete_workspace_and_final_prompt_paths(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name) / "workspace"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "create",
                        "--input",
                        "probabilidade condicional",
                        "--workspace",
                        str(workspace),
                    ]
                )
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue((workspace / "ingest" / "source_manifest.json").is_file())
            self.assertTrue((workspace / "ledgers" / "unit_ledger.v0.json").is_file())
            for raw_path in payload["prompts"]:
                prompt = Path(raw_path)
                self.assertTrue(prompt.is_file())
                self.assertTrue(prompt.is_relative_to(workspace))

    def test_search_cli_output_uses_preview_but_points_to_full_report(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name)
            values = [f"Q-{index:03d}" for index in range(100)]
            compact = _compact_search_output(
                workspace,
                {
                    "queries_pending_ready": 100,
                    "pending_ready_query_ids": values,
                    "pending_localization_query_ids": [],
                },
            )
            self.assertNotIn("pending_ready_query_ids", compact)
            preview = compact["pending_ready_query_ids_preview"]
            self.assertIsInstance(preview, list)
            assert isinstance(preview, list)
            self.assertEqual(len(preview), 20)
            self.assertTrue(compact["pending_ready_query_ids_preview_truncated"])
            self.assertTrue(str(compact["full_report"]).endswith("search_report.json"))

    def test_search_cli_forwards_explicit_route_policy_opt_ins(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name) / "workspace"
            stdout = io.StringIO()
            with patch(
                "projeto_e_video.cli.manual_search", return_value={}
            ) as called, redirect_stdout(stdout):
                code = main(
                    [
                        "search",
                        "--workspace",
                        str(workspace),
                        "--provider",
                        "manual",
                        "--include-optional",
                        "--include-control",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertTrue(called.call_args.kwargs["include_optional"])
            self.assertTrue(called.call_args.kwargs["include_control"])


if __name__ == "__main__":
    unittest.main()
