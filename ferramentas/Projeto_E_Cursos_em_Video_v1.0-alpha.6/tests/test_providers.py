from __future__ import annotations

import tempfile
import unittest
import json
import subprocess
import copy
from pathlib import Path
from unittest import mock

from projeto_e_video.providers import (
    canonical_video_url,
    import_candidates,
    manual_search,
    validate_candidates,
    yt_dlp_search,
)
from projeto_e_video.ingest import ingest
from projeto_e_video.planning import create_plan, import_map
from projeto_e_video.util import atomic_write_json, read_json
from tests.helpers import verified_workspace


class ProviderTests(unittest.TestCase):
    def bibliographic_workspace(self, base: Path) -> tuple[Path, dict]:
        workspace, ledger = verified_workspace(base)
        refined = copy.deepcopy(ledger)
        refined["units"][0]["search_identity"].update(
            {
                "creator": "Joseph Blitzstein",
                "work": "Introduction to Probability",
                "chapter": "Chapter 4",
            }
        )
        path = base / "bibliographic-map.json"
        atomic_write_json(path, refined)
        return workspace, import_map(workspace, path)

    def policy_workspace(self, base: Path) -> tuple[Path, dict]:
        source = base / "policies.md"
        source.write_text(
            "# Obrigatório principal\nResolva o exercício e confira a resposta.\n\n"
            "# Opcional avançado\nResolva o exercício e confira a resposta.\n\n"
            "# Controle fácil\nResolva o exercício e confira a resposta.",
            encoding="utf-8",
        )
        workspace = base / "workspace"
        workspace.mkdir()
        ingest(str(source), workspace)
        refined = create_plan(workspace)
        policies = ("REQUIRED", "OPTIONAL", "CONTROL_NO_AUTOMATIC")
        for unit, policy in zip(refined["units"], policies, strict=True):
            unit["verification_state"] = "VERIFIED_BY_HUMAN"
            unit["route_policy"] = policy
            unit["search_identity"]["source_language"] = "pt"
            unit["search_identity"]["technical_terms"] = [unit["title"]]
        path = base / "policy-map.json"
        atomic_write_json(path, refined)
        return workspace, import_map(workspace, path)

    def test_canonical_youtube_url_discards_tracking(self) -> None:
        value = canonical_video_url(
            "https://www.youtube.com/watch?v=abc123def45&utm_source=x&si=secret"
        )
        self.assertEqual(value, "https://www.youtube.com/watch?v=abc123def45")

    def test_youtube_short_link_and_watch_link_have_same_identity(self) -> None:
        short = canonical_video_url("https://youtu.be/abc123def45?si=tracking")
        watch = canonical_video_url(
            "https://m.youtube.com/watch?v=abc123def45&list=ignored"
        )
        self.assertEqual(short, watch)

    def test_youtube_placeholder_is_rejected_as_non_video(self) -> None:
        with self.assertRaisesRegex(ValueError, "placeholders"):
            canonical_video_url(
                "https://www.youtube.com/watch?v=AnaliseRealSupremo"
            )

    def test_youtube_playlist_without_video_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "vídeo direto"):
            canonical_video_url("https://www.youtube.com/playlist?list=PL123")

    def test_private_candidate_url_is_rejected_before_collection(self) -> None:
        with self.assertRaisesRegex(ValueError, "privada"):
            canonical_video_url("http://127.0.0.1/video")

    def test_open_language_expansion_gets_stable_query_id(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            unit = ledger["units"][0]
            queries = read_json(workspace / "ledgers" / "search_queries.json")
            document = validate_candidates(
                {
                    "schema_name": "projeto-e-video.candidates",
                    "schema_version": 2,
                    "search_scope": "GLOBAL_OPEN",
                    "search_attempts": [
                        {
                            "query_id": "TEMP-ja-01",
                            "origin": "OPEN_EXPANSION",
                            "unit_id": unit["unit_id"],
                            "language": "ja",
                            "query": "演習問題をステップごとに解説",
                            "status": "COMPLETED",
                            "result_count": 1,
                            "error": None,
                        }
                    ],
                    "candidates": [
                        {
                            "unit_ids": [unit["unit_id"]],
                            "url": "https://www.youtube.com/watch?v=abcdefghijk",
                            "title": "候補",
                            "channel": "講師",
                            "language": "ja",
                            "language_basis": "PLATFORM_METADATA",
                            "discovery_languages": ["ja"],
                            "provider": "browser",
                            "metadata_observed": ["TITLE", "LANGUAGE"],
                            "query_ids": ["TEMP-ja-01"],
                        }
                    ],
                },
                ledger,
                query_doc=queries,
            )
            attempt = document["search_attempts"][0]
            self.assertRegex(attempt["query_id"], r"^QX-[0-9a-f]{12}$")
            self.assertEqual(attempt["origin"], "OPEN_EXPANSION")
            self.assertEqual(document["candidates"][0]["query_ids"], [attempt["query_id"]])

    def test_duplicate_url_is_merged_with_stable_id(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            _, ledger = verified_workspace(
                base,
                text="# A\nDefina o conceito.\n\n# B\nExplique outro conceito.",
            )
            rows = []
            for unit in ledger["units"]:
                rows.append(
                    {
                        "unit_ids": [unit["unit_id"]],
                        "url": "https://video.example/a?utm_source=teste",
                        "title": "Mesmo vídeo",
                        "channel": "Canal",
                        "language": "pt",
                        "duration_seconds": 10,
                        "provider": "manual",
                        "metadata_observed": ["TITLE"],
                    }
                )
            document = validate_candidates(
                {
                    "schema_name": "projeto-e-video.candidates",
                    "schema_version": 1,
                    "candidates": rows,
                },
                ledger,
            )
            self.assertEqual(document["candidate_count"], 1)
            self.assertEqual(len(document["candidates"][0]["unit_ids"]), 2)
            self.assertRegex(document["candidates"][0]["candidate_id"], r"^VID-[0-9a-f]{12}$")

    def test_candidate_cannot_self_approve(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            _, ledger = verified_workspace(base)
            with self.assertRaisesRegex(ValueError, "autoaprovação"):
                validate_candidates(
                    {
                        "schema_name": "projeto-e-video.candidates",
                        "schema_version": 1,
                        "approved": True,
                        "candidates": [],
                    },
                    ledger,
                )

    def test_manual_search_creates_empty_metadata_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, _ = verified_workspace(base)
            report = manual_search(workspace)
            self.assertEqual(report["candidate_count"], 0)
            self.assertTrue((workspace / "prompts" / "03_INVENTARIAR_AUDIO.md").is_file())
            self.assertTrue((workspace / "prompts" / "04_AUDITAR_VIDEOS.md").is_file())

    def test_yt_dlp_absence_has_manual_fallback_message(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, _ = verified_workspace(base)
            with mock.patch("projeto_e_video.providers.yt_dlp_command", return_value=None):
                with self.assertRaisesRegex(ValueError, "provider manual"):
                    yt_dlp_search(workspace)

    def test_search_is_blocked_before_verified_map(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace = base / "workspace"
            workspace.mkdir()
            ingest("cálculo diferencial", workspace)
            create_plan(workspace)
            with self.assertRaisesRegex(ValueError, "V1_VERIFIED"):
                manual_search(workspace)

    def test_query_language_is_not_assigned_to_video(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, _ = verified_workspace(base)
            payload = {
                "entries": [
                    {
                        "id": "abc123def45",
                        "title": "Vídeo sem idioma declarado",
                        "channel": "Canal",
                        "duration": 120,
                    }
                ]
            }
            completed = subprocess.CompletedProcess(
                args=["yt-dlp"],
                returncode=0,
                stdout=json.dumps(payload).encode(),
                stderr=b"",
            )
            with mock.patch(
                "projeto_e_video.providers.yt_dlp_command", return_value=["yt-dlp"]
            ), mock.patch(
                "projeto_e_video.providers.run_command", return_value=completed
            ):
                yt_dlp_search(workspace, limit=1, max_queries=1)
            document = read_json(workspace / "ledgers" / "candidates.json")
            candidate = document["candidates"][0]
            self.assertEqual(candidate["language"], "und")
            self.assertEqual(candidate["language_basis"], "UNKNOWN")
            self.assertEqual(candidate["discovery_languages"], ["pt"])
            self.assertEqual(document["search_attempts"][0]["origin"], "SEED_PLAN")

    def test_automatic_search_resumes_without_overwriting_progress(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, _ = self.bibliographic_workspace(base)
            calls = 0

            def response(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
                nonlocal calls
                calls += 1
                payload = {
                    "entries": [
                        {
                            "id": f"video{calls:06d}",
                            "title": f"Introduction to Probability Chapter 4 — {calls}",
                            "channel": "Harvard",
                            "duration": 120,
                        }
                    ]
                }
                return subprocess.CompletedProcess(
                    args=["yt-dlp"],
                    returncode=0,
                    stdout=json.dumps(payload).encode(),
                    stderr=b"",
                )

            with mock.patch(
                "projeto_e_video.providers.yt_dlp_command", return_value=["yt-dlp"]
            ), mock.patch(
                "projeto_e_video.providers.run_command", side_effect=response
            ):
                first = yt_dlp_search(workspace, limit=1, max_queries=1)
                second = yt_dlp_search(workspace, limit=1, max_queries=1)
            document = read_json(workspace / "ledgers" / "candidates.json")
            self.assertEqual(calls, 2)
            self.assertEqual(first["queries_completed"], 1)
            self.assertEqual(second["queries_completed"], 2)
            self.assertEqual(document["candidate_count"], 2)
            self.assertEqual(len(document["search_attempts"]), 2)

    def test_incremental_import_preserves_search_history_and_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = self.bibliographic_workspace(base)
            payload = {
                "entries": [
                    {
                        "id": "first-video",
                        "title": "First candidate",
                        "channel": "Harvard",
                        "duration": 120,
                    }
                ]
            }
            completed = subprocess.CompletedProcess(
                args=["yt-dlp"],
                returncode=0,
                stdout=json.dumps(payload).encode(),
                stderr=b"",
            )
            with mock.patch(
                "projeto_e_video.providers.yt_dlp_command", return_value=["yt-dlp"]
            ), mock.patch(
                "projeto_e_video.providers.run_command", return_value=completed
            ):
                yt_dlp_search(workspace, limit=1, max_queries=1)
            previous = read_json(workspace / "ledgers" / "candidates.json")
            query_id = previous["search_attempts"][0]["query_id"]
            incoming_path = base / "incremental.json"
            atomic_write_json(
                incoming_path,
                {
                    "schema_name": "projeto-e-video.candidates",
                    "schema_version": 3,
                    "search_scope": "GLOBAL_OPEN",
                    "search_attempts": [],
                    "candidates": [
                        {
                            "unit_ids": [ledger["units"][0]["unit_id"]],
                            "url": "https://www.youtube.com/watch?v=secnd-video",
                            "title": "Second candidate",
                            "channel": "Another channel",
                            "language": "und",
                            "language_basis": "UNKNOWN",
                            "discovery_languages": ["en"],
                            "provider": "browser",
                            "metadata_observed": ["TITLE", "CHANNEL"],
                            "query_ids": [query_id],
                        }
                    ],
                },
            )
            merged = import_candidates(workspace, incoming_path)
            self.assertEqual(len(merged["search_attempts"]), 1)
            self.assertEqual(merged["search_attempts"][0]["query_id"], query_id)
            self.assertEqual(merged["candidate_count"], 2)

    def test_search_progress_does_not_mix_open_expansions_with_seed_counts(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = self.bibliographic_workspace(base)
            unit = ledger["units"][0]
            expansion_path = base / "expansion.json"
            atomic_write_json(
                expansion_path,
                {
                    "schema_name": "projeto-e-video.candidates",
                    "schema_version": 3,
                    "search_scope": "GLOBAL_OPEN",
                    "search_attempts": [
                        {
                            "query_id": "temporary-expansion",
                            "origin": "OPEN_EXPANSION",
                            "unit_id": unit["unit_id"],
                            "language": "en",
                            "query": "Harvard Stat 110 expectation",
                            "status": "COMPLETED",
                            "result_count": 0,
                            "error": None,
                        }
                    ],
                    "candidates": [],
                },
            )
            import_candidates(workspace, expansion_path)
            imported_report = read_json(
                workspace / "ledgers" / "search_report.json"
            )
            self.assertEqual(imported_report["provider"], "import-candidates")
            self.assertEqual(imported_report["queries_completed"], 0)
            self.assertEqual(imported_report["open_expansion_attempts_completed"], 1)
            completed = subprocess.CompletedProcess(
                args=["yt-dlp"],
                returncode=0,
                stdout=json.dumps({"entries": []}).encode(),
                stderr=b"",
            )
            with mock.patch(
                "projeto_e_video.providers.yt_dlp_command", return_value=["yt-dlp"]
            ), mock.patch(
                "projeto_e_video.providers.run_command", return_value=completed
            ):
                report = yt_dlp_search(workspace, max_queries=1)
            self.assertEqual(report["queries_completed"], 1)
            self.assertEqual(report["open_expansion_attempts_completed"], 1)
            self.assertEqual(report["search_attempts_total"], 2)
            self.assertEqual(
                report["queries_completed"] + report["queries_pending_ready"],
                report["queries_ready"],
            )

    def test_failed_search_is_retried_only_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, _ = verified_workspace(base)
            failed = subprocess.CompletedProcess(
                args=["yt-dlp"], returncode=1, stdout=b"", stderr=b"rate limited"
            )
            recovered = subprocess.CompletedProcess(
                args=["yt-dlp"],
                returncode=0,
                stdout=json.dumps({"entries": []}).encode(),
                stderr=b"",
            )
            with mock.patch(
                "projeto_e_video.providers.yt_dlp_command", return_value=["yt-dlp"]
            ), mock.patch(
                "projeto_e_video.providers.run_command",
                side_effect=[failed, recovered, recovered],
            ) as runner:
                yt_dlp_search(workspace, max_queries=1)
                failed_query_id = read_json(
                    workspace / "ledgers" / "candidates.json"
                )["search_attempts"][0]["query_id"]
                no_retry = yt_dlp_search(workspace, max_queries=1)
                still_failed = {
                    row["query_id"]: row["status"]
                    for row in read_json(
                        workspace / "ledgers" / "candidates.json"
                    )["search_attempts"]
                }
                retried = yt_dlp_search(
                    workspace, max_queries=1, retry_failed=True
                )
            self.assertEqual(runner.call_count, 3)
            self.assertEqual(no_retry["queries_executed_this_run"], 1)
            self.assertEqual(still_failed[failed_query_id], "FAILED")
            self.assertEqual(retried["queries_failed"], 0)

    def test_search_filters_one_round_without_hiding_global_pending_work(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = self.bibliographic_workspace(base)
            completed = subprocess.CompletedProcess(
                args=["yt-dlp"],
                returncode=0,
                stdout=json.dumps({"entries": []}).encode(),
                stderr=b"",
            )
            with mock.patch(
                "projeto_e_video.providers.yt_dlp_command", return_value=["yt-dlp"]
            ), mock.patch(
                "projeto_e_video.providers.run_command", return_value=completed
            ) as runner:
                report = yt_dlp_search(
                    workspace,
                    max_queries=10,
                    languages=["en"],
                    unit_ids=[ledger["units"][0]["unit_id"]],
                    search_stages=["EXACT_OBJECT"],
                )
            self.assertEqual(runner.call_count, 2)
            self.assertEqual(report["queries_eligible_for_filters"], 2)
            self.assertEqual(report["queries_executed_this_run"], 2)
            self.assertGreater(report["queries_pending_ready"], 1)
            self.assertEqual(report["filters"]["languages"], ["en"])

    def test_automatic_search_defaults_to_required_and_explicit_id_opts_in(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = self.policy_workspace(base)
            by_policy = {
                unit["route_policy"]: unit["unit_id"] for unit in ledger["units"]
            }
            completed = subprocess.CompletedProcess(
                args=["yt-dlp"],
                returncode=0,
                stdout=json.dumps({"entries": []}).encode(),
                stderr=b"",
            )
            with mock.patch(
                "projeto_e_video.providers.yt_dlp_command", return_value=["yt-dlp"]
            ), mock.patch(
                "projeto_e_video.providers.run_command", return_value=completed
            ):
                default_report = yt_dlp_search(
                    workspace, max_queries=100, languages=["pt"]
                )
                first_attempts = read_json(
                    workspace / "ledgers" / "candidates.json"
                )["search_attempts"]
                query_by_id = {
                    row["query_id"]: row
                    for row in read_json(
                        workspace / "ledgers" / "search_queries.json"
                    )["queries"]
                }
                self.assertTrue(first_attempts)
                self.assertEqual(
                    {query_by_id[row["query_id"]]["unit_id"] for row in first_attempts},
                    {by_policy["REQUIRED"]},
                )
                explicit_report = yt_dlp_search(
                    workspace,
                    max_queries=100,
                    languages=["pt"],
                    unit_ids=[by_policy["OPTIONAL"]],
                )
            self.assertEqual(default_report["progress_scope"], "REQUIRED")
            self.assertEqual(
                default_report["policy_progress"]["OPTIONAL"]["queries_completed"],
                0,
            )
            self.assertGreater(
                explicit_report["policy_progress"]["OPTIONAL"]["queries_completed"],
                0,
            )
            self.assertEqual(
                explicit_report["policy_progress"]["CONTROL_NO_AUTOMATIC"][
                    "queries_completed"
                ],
                0,
            )

    def test_manual_prompt_scopes_optional_and_control_by_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = self.policy_workspace(base)
            by_policy = {
                unit["route_policy"]: unit for unit in ledger["units"]
            }
            default_report = manual_search(workspace)
            prompt_path = workspace / "prompts" / "02_BUSCAR_CANDIDATOS.md"
            default_prompt = prompt_path.read_text(encoding="utf-8")
            self.assertEqual(default_report["filters"]["selected_unit_count"], 1)
            self.assertIn(by_policy["REQUIRED"]["title"], default_prompt)
            self.assertNotIn(by_policy["OPTIONAL"]["title"], default_prompt)
            self.assertNotIn(by_policy["CONTROL_NO_AUTOMATIC"]["title"], default_prompt)

            optional_report = manual_search(
                workspace, unit_ids=[by_policy["OPTIONAL"]["unit_id"]]
            )
            optional_prompt = prompt_path.read_text(encoding="utf-8")
            self.assertEqual(optional_report["filters"]["selected_unit_count"], 1)
            self.assertIn(by_policy["OPTIONAL"]["title"], optional_prompt)
            self.assertNotIn(by_policy["REQUIRED"]["title"], optional_prompt)

    def test_policy_flags_are_explicit_bulk_opt_ins(self) -> None:
        cases = (
            ({"include_optional": True}, {"REQUIRED", "OPTIONAL"}),
            (
                {"include_control": True},
                {"REQUIRED", "CONTROL_NO_AUTOMATIC"},
            ),
        )
        for options, expected_policies in cases:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as name:
                base = Path(name)
                workspace, ledger = self.policy_workspace(base)
                policy_by_unit = {
                    unit["unit_id"]: unit["route_policy"]
                    for unit in ledger["units"]
                }
                completed = subprocess.CompletedProcess(
                    args=["yt-dlp"],
                    returncode=0,
                    stdout=json.dumps({"entries": []}).encode(),
                    stderr=b"",
                )
                with mock.patch(
                    "projeto_e_video.providers.yt_dlp_command",
                    return_value=["yt-dlp"],
                ), mock.patch(
                    "projeto_e_video.providers.run_command",
                    return_value=completed,
                ):
                    report = yt_dlp_search(
                        workspace,
                        max_queries=100,
                        languages=["pt"],
                        include_optional=options.get("include_optional", False),
                        include_control=options.get("include_control", False),
                    )
                query_by_id = {
                    row["query_id"]: row
                    for row in read_json(
                        workspace / "ledgers" / "search_queries.json"
                    )["queries"]
                }
                attempts = read_json(
                    workspace / "ledgers" / "candidates.json"
                )["search_attempts"]
                observed_policies = {
                    policy_by_unit[query_by_id[row["query_id"]]["unit_id"]]
                    for row in attempts
                }
                self.assertEqual(observed_policies, expected_policies)
                self.assertEqual(
                    set(report["filters"]["selected_route_policies"]),
                    expected_policies,
                )

    def test_factorial_moment_collision_is_flagged_as_metadata_noise(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            ledger["units"][0]["search_identity"]["notation"] = ["E(X!)"]
            row = validate_candidates(
                {
                    "schema_name": "projeto-e-video.candidates",
                    "schema_version": 3,
                    "search_scope": "GLOBAL_OPEN",
                    "search_attempts": [],
                    "candidates": [
                        {
                            "unit_ids": [ledger["units"][0]["unit_id"]],
                            "url": "https://video.example/factorial-moment",
                            "title": "Factorial moments: E[X(X-1)]",
                            "channel": "Probability",
                            "language": "en",
                            "provider": "manual",
                            "metadata_observed": ["TITLE"],
                        }
                    ],
                },
                ledger,
            )["candidates"][0]
            self.assertEqual(row["metadata_triage"]["status"], "RUIDO_PROVAVEL")
            self.assertTrue(row["metadata_triage"]["collision_risks"])

    def test_localized_search_identity_prioritizes_review_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            _, ledger = verified_workspace(base)
            unit = ledger["units"][0]
            unit["search_identity"]["localized_terms"] = [
                {
                    "language": "es",
                    "terms": ["teorema de Bayes ejercicio resuelto"],
                }
            ]
            row = validate_candidates(
                {
                    "schema_name": "projeto-e-video.candidates",
                    "schema_version": 3,
                    "search_scope": "GLOBAL_OPEN",
                    "search_attempts": [],
                    "candidates": [
                        {
                            "unit_ids": [unit["unit_id"]],
                            "url": "https://video.example/bayes-es",
                            "title": "Teorema de Bayes ejercicio resuelto",
                            "channel": "Curso de probabilidad",
                            "language": "es",
                            "provider": "manual",
                            "metadata_observed": ["TITLE"],
                        }
                    ],
                },
                ledger,
            )["candidates"][0]
            triage = row["metadata_triage"]
            self.assertTrue(
                any(
                    "localized_terms[es]" in value
                    for value in triage["fingerprint_matches"]
                )
            )
            self.assertTrue(triage["metadata_only"])
            self.assertNotIn("eligible_for_course", row)


if __name__ == "__main__":
    unittest.main()
