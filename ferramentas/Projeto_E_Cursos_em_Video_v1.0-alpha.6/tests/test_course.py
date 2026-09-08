from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from projeto_e_video.course import build_course
from projeto_e_video.audio import import_audio_inventory
from projeto_e_video.providers import import_candidates
from projeto_e_video.planning import import_map
from projeto_e_video.util import atomic_write_json, atomic_write_text, read_json
from projeto_e_video.validation import validate_workspace
from tests.helpers import add_candidate, observation, run_audit, verified_workspace


class CourseTests(unittest.TestCase):
    def test_exact_real_video_is_released_with_merged_useful_time(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            candidate = add_candidate(base, workspace, ledger)
            unit = ledger["units"][0]
            run_audit(base, workspace, [observation(workspace, candidate, unit)])
            course = build_course(workspace)
            self.assertEqual(course["course_state"], "COBERTA")
            self.assertEqual(course["released_unit_count"], 1)
            self.assertEqual(course["total_useful_seconds"], 80)
            self.assertTrue(course["routes"][0]["released"])
            self.assertEqual(len(course["routes"][0]["video"]["segments"]), 1)
            self.assertTrue((workspace / "course" / "index.html").is_file())
            self.assertTrue(validate_workspace(workspace)["valid"])

    def test_partial_route_keeps_gap_and_counts_zero_time(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            candidate = add_candidate(base, workspace, ledger)
            unit = ledger["units"][0]
            first = unit["required_steps"][0]["step_id"]
            run_audit(
                base,
                workspace,
                [observation(workspace, candidate, unit, covered_steps=[first])],
            )
            course = build_course(workspace)
            self.assertEqual(course["course_state"], "PARCIAL")
            self.assertEqual(course["total_useful_seconds"], 0)
            self.assertIsNone(course["routes"][0]["video"])
            self.assertTrue(course["gaps"])

    def test_harder_video_is_optional_and_does_not_close_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            candidate = add_candidate(base, workspace, ledger)
            unit = ledger["units"][0]
            obs = observation(
                workspace,
                candidate,
                unit,
                match="EQUIVALENT",
                rationale="Os dados mudam, mas estrutura, decisões, hipóteses e verificação seguem iguais.",
                missing_prerequisites=["Teoria espectral"],
            )
            run_audit(base, workspace, [obs])
            course = build_course(workspace)
            optional = course["routes"][0]["optional_advanced_route"]
            self.assertTrue(optional["student_opt_in_required"])
            self.assertFalse(optional["counts_as_coverage"])
            self.assertEqual(course["released_unit_count"], 0)

    def test_fixture_never_becomes_real_course(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            candidate = add_candidate(base, workspace, ledger, fixture=True)
            unit = ledger["units"][0]
            run_audit(
                base,
                workspace,
                [observation(workspace, candidate, unit, fixture=True)],
                fixture=True,
            )
            course = build_course(workspace)
            self.assertEqual(course["course_state"], "DEMONSTRACAO_FIXTURE")
            self.assertEqual(course["released_unit_count"], 0)
            self.assertEqual(course["total_useful_seconds"], 0)

    def test_build_rederives_and_ignores_tampered_audit(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            candidate = add_candidate(base, workspace, ledger)
            unit = ledger["units"][0]
            first = unit["required_steps"][0]["step_id"]
            run_audit(
                base,
                workspace,
                [observation(workspace, candidate, unit, covered_steps=[first])],
            )
            forged = read_json(workspace / "audit" / "audit.json")
            forged["candidate_results"][0]["classification"] = "EXATO"
            forged["candidate_results"][0]["eligible_for_course"] = True
            forged["unit_results"][0]["classification"] = "EXATO"
            forged["unit_results"][0]["eligible_for_course"] = True
            atomic_write_json(workspace / "audit" / "audit.json", forged)
            course = build_course(workspace)
            self.assertEqual(course["course_state"], "PARCIAL")
            self.assertEqual(course["routes"][0]["classification"], "PARCIAL")

    def test_validation_detects_tampered_course_and_html(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            candidate = add_candidate(base, workspace, ledger)
            unit = ledger["units"][0]
            run_audit(base, workspace, [observation(workspace, candidate, unit)])
            build_course(workspace)
            forged = read_json(workspace / "course" / "course.json")
            forged["routes"][0]["objective"] = "Objetivo adulterado"
            atomic_write_json(workspace / "course" / "course.json", forged)
            with self.assertRaisesRegex(ValueError, "reconstrução determinística"):
                validate_workspace(workspace, write_report=False)

            build_course(workspace)
            atomic_write_text(workspace / "course" / "index.html", "<p>adulterado</p>\n")
            with self.assertRaisesRegex(ValueError, "index.html diverge"):
                validate_workspace(workspace, write_report=False)

    def test_two_strict_components_can_cover_one_unit(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            unit = ledger["units"][0]
            candidate_file = base / "two-candidates.json"
            atomic_write_json(
                candidate_file,
                {
                    "schema_name": "projeto-e-video.candidates",
                    "schema_version": 3,
                    "search_scope": "GLOBAL_OPEN",
                    "search_attempts": [],
                    "candidates": [
                        {
                            "unit_ids": [unit["unit_id"]],
                            "url": "https://video.example/parte-a",
                            "title": "Parte A",
                            "channel": "Professor A",
                            "language": "pt",
                            "language_basis": "MANUAL_OBSERVATION",
                            "discovery_languages": ["pt"],
                            "duration_seconds": 600,
                            "provider": "test",
                            "metadata_observed": ["TITLE"],
                        },
                        {
                            "unit_ids": [unit["unit_id"]],
                            "url": "https://video.example/parte-b",
                            "title": "Parte B",
                            "channel": "Professor B",
                            "language": "en",
                            "language_basis": "MANUAL_OBSERVATION",
                            "discovery_languages": ["en"],
                            "duration_seconds": 600,
                            "provider": "test",
                            "metadata_observed": ["TITLE"],
                        },
                    ],
                },
            )
            candidate_doc = import_candidates(workspace, candidate_file)
            inventory_file = base / "two-audio.json"
            records = []
            for candidate in candidate_doc["candidates"]:
                language = "en" if candidate["title"] == "Parte B" else "pt-BR"
                records.append(
                    {
                        "candidate_id": candidate["candidate_id"],
                        "candidate_url": candidate["url"],
                        "provider": "test",
                        "inspected_at": "test",
                        "tracks": [
                            {
                                "language": language,
                                "label": f"faixa {language}",
                                "audio_kind_hint": "ORIGINAL",
                                "metadata_basis": ["TEST"],
                                "is_default": True,
                                "formats": [],
                            }
                        ],
                        "subtitles": [],
                        "warnings": [],
                    }
                )
            atomic_write_json(
                inventory_file,
                {
                    "schema_name": "projeto-e-video.audio-inventory",
                    "schema_version": 2,
                    "records": records,
                },
            )
            import_audio_inventory(workspace, inventory_file)
            steps = [row["step_id"] for row in unit["required_steps"]]
            first_half = steps[: max(1, len(steps) // 2)]
            second_half = [row for row in steps if row not in first_half]
            observations = []
            for candidate, covered, target in (
                (
                    next(row for row in candidate_doc["candidates"] if row["title"] == "Parte A"),
                    first_half,
                    "pt",
                ),
                (
                    next(row for row in candidate_doc["candidates"] if row["title"] == "Parte B"),
                    second_half,
                    "en",
                ),
            ):
                observations.append(
                    observation(
                        workspace,
                        candidate,
                        unit,
                        covered_steps=covered,
                        target_language=target,
                    )
                )
            audit = run_audit(base, workspace, observations)
            unit_result = audit["unit_results"][0]
            self.assertEqual(unit_result["coverage_mode"], "COMPOSITE")
            self.assertTrue(unit_result["eligible_for_course"])
            course = build_course(workspace)
            route = course["routes"][0]
            self.assertTrue(route["released"])
            self.assertEqual(len(route["videos"]), 2)
            self.assertIsNone(route["video"])
            self.assertEqual(course["total_useful_seconds"], 160)
            html = (workspace / "course" / "index.html").read_text(encoding="utf-8")
            self.assertEqual(html.count("Parte A"), 1)
            self.assertEqual(html.count("Parte B"), 1)
            self.assertTrue(validate_workspace(workspace)["valid"])

    def test_optional_and_easy_control_are_never_auto_recommended(self) -> None:
        for policy in ("OPTIONAL", "CONTROL_NO_AUTOMATIC"):
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as name:
                base = Path(name)
                workspace, ledger = verified_workspace(base)
                refined = read_json(workspace / "ledgers" / "unit_ledger.json")
                refined["units"][0]["route_policy"] = policy
                map_file = base / "policy-map.json"
                atomic_write_json(map_file, refined)
                ledger = import_map(workspace, map_file)
                candidate = add_candidate(base, workspace, ledger)
                unit = ledger["units"][0]
                run_audit(base, workspace, [observation(workspace, candidate, unit)])
                course = build_course(workspace)
                route = course["routes"][0]
                self.assertFalse(route["released"])
                self.assertFalse(route["automatically_recommended"])
                self.assertTrue(route["optional_available"])
                self.assertEqual(len(route["optional_videos"]), 1)
                self.assertEqual(course["required_unit_count"], 0)
                self.assertEqual(course["released_unit_count"], 0)
                self.assertEqual(course["optional_available_count"], 1)
                self.assertEqual(course["course_state"], "COBERTA")
                self.assertTrue(validate_workspace(workspace)["valid"])


if __name__ == "__main__":
    unittest.main()
