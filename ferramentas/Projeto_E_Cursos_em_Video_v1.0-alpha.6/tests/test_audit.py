from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from projeto_e_video.audit import audit
from projeto_e_video.util import atomic_write_json, read_json
from tests.helpers import add_candidate, observation, run_audit, verified_workspace


class AuditTests(unittest.TestCase):
    def scenario(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path, dict, dict]:
        temp = tempfile.TemporaryDirectory()
        base = Path(temp.name)
        workspace, ledger = verified_workspace(base)
        candidate = add_candidate(base, workspace, ledger)
        unit = ledger["units"][0]
        return temp, base, workspace, candidate, unit

    def test_exact_requires_and_accepts_internal_evidence(self) -> None:
        temp, base, workspace, candidate, unit = self.scenario()
        with temp:
            result = run_audit(base, workspace, [observation(workspace, candidate, unit)])
            candidate_result = result["candidate_results"][0]
            self.assertEqual(candidate_result["classification"], "EXATO")
            self.assertTrue(candidate_result["eligible_for_course"])
            # 20–80 e 70–100 se unem: 80 segundos, não 90.
            self.assertEqual(candidate_result["useful_seconds"], 80)

    def test_rigorous_equivalent_needs_explanation(self) -> None:
        temp, base, workspace, candidate, unit = self.scenario()
        with temp:
            obs = observation(
                workspace,
                candidate,
                unit,
                match="EQUIVALENT",
                rationale="Mudam apenas os números; hipóteses, método, decisões e conferência permanecem estruturalmente iguais.",
            )
            result = run_audit(base, workspace, [obs])
            self.assertEqual(
                result["candidate_results"][0]["classification"],
                "EQUIVALENTE_RIGOROSO",
            )

    def test_missing_step_is_partial(self) -> None:
        temp, base, workspace, candidate, unit = self.scenario()
        with temp:
            first = unit["required_steps"][0]["step_id"]
            obs = observation(workspace, candidate, unit, covered_steps=[first])
            result = run_audit(base, workspace, [obs])
            self.assertEqual(result["candidate_results"][0]["classification"], "PARCIAL")

    def test_theory_does_not_close_resolution(self) -> None:
        temp, base, workspace, candidate, unit = self.scenario()
        with temp:
            obs = observation(workspace, candidate, unit, match="THEORY")
            result = run_audit(base, workspace, [obs])
            self.assertEqual(result["candidate_results"][0]["classification"], "TEORIA_APENAS")

    def test_conflict_is_preserved_as_error(self) -> None:
        temp, base, workspace, candidate, unit = self.scenario()
        with temp:
            obs = observation(
                workspace,
                candidate,
                unit,
                match="CONFLICT",
                conflict={
                    "description": "O professor troca o sinal e conclui um valor matematicamente incompatível.",
                    "timestamp_seconds": 71,
                },
            )
            result = run_audit(base, workspace, [obs])
            self.assertEqual(result["candidate_results"][0]["classification"], "ERRO_MATEMATICO")

    def test_unevidenced_conflict_is_not_promoted_to_error_claim(self) -> None:
        temp, base, workspace, candidate, unit = self.scenario()
        with temp:
            obs = observation(
                workspace,
                candidate,
                unit,
                match="CONFLICT",
                methods=[],
                identity=False,
                with_timestamps=False,
                conflict={
                    "description": "O título parece sugerir uma conclusão errada, sem inspeção interna.",
                    "timestamp_seconds": 0,
                },
            )
            result = run_audit(base, workspace, [obs])
            self.assertEqual(result["candidate_results"][0]["classification"], "NAO_VERIFICAVEL")

    def test_video_without_transcript_can_use_verified_speech_and_frame(self) -> None:
        temp, base, workspace, candidate, unit = self.scenario()
        with temp:
            obs = observation(
                workspace,
                candidate,
                unit,
                methods=["FALA_VERIFICADA", "FRAME"],
                transcript_available=False,
            )
            result = run_audit(base, workspace, [obs])
            self.assertEqual(result["candidate_results"][0]["classification"], "EXATO")

    def test_each_timestamp_requires_local_speech_description(self) -> None:
        temp, base, workspace, candidate, unit = self.scenario()
        with temp:
            obs = observation(workspace, candidate, unit)
            obs["timestamps"][0].pop("speech_or_transcript_observed")
            with self.assertRaisesRegex(ValueError, "fala da janela"):
                run_audit(base, workspace, [obs])

    def test_visual_only_unverifiable_observation_can_record_missing_speech(self) -> None:
        temp, base, workspace, candidate, unit = self.scenario()
        with temp:
            obs = observation(
                workspace,
                candidate,
                unit,
                match="UNVERIFIABLE",
                methods=["FRAME"],
                transcript_available=False,
                with_audio_review=False,
            )
            for timestamp in obs["timestamps"]:
                timestamp["speech_or_transcript_observed"] = ""
            row = run_audit(base, workspace, [obs])["candidate_results"][0]
            self.assertEqual(row["classification"], "NAO_VERIFICAVEL")
            self.assertFalse(row["acceptance_gates"]["speech_or_transcript_verified"])

    def test_same_audiovisual_window_cannot_be_recycled_across_units(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(
                base,
                text=(
                    "# Exercício A\nResolva o primeiro problema e confira.\n\n"
                    "# Exercício B\nResolva o segundo problema e confira."
                ),
            )
            candidate = add_candidate(base, workspace, ledger)
            observations = [
                observation(workspace, candidate, unit) for unit in ledger["units"]
            ]
            result = run_audit(base, workspace, observations)
            rows = result["candidate_results"]
            self.assertEqual(len(rows), 2)
            self.assertTrue(
                all(row["classification"] == "NAO_VERIFICAVEL" for row in rows)
            )
            self.assertTrue(
                all(
                    "unit_specific_evidence" in row["failed_gates"]
                    and row["evidence_reused_across_unit_ids"]
                    for row in rows
                )
            )

    def test_artifacts_are_bound_to_their_candidate_directory(self) -> None:
        temp, base, workspace, candidate, unit = self.scenario()
        with temp:
            obs = observation(workspace, candidate, unit)
            obs["artifacts"][0]["path"] = "evidence/assets/VID-outro/transcript.txt"
            with self.assertRaisesRegex(ValueError, "evidence/assets"):
                run_audit(base, workspace, [obs])

    def test_audio_must_cover_every_required_step(self) -> None:
        temp, base, workspace, candidate, unit = self.scenario()
        with temp:
            obs = observation(workspace, candidate, unit)
            steps = [row["step_id"] for row in unit["required_steps"]]
            audio_id = obs["audio_reviews"][0]["audio_artifact_ids"][0]
            obs["timestamps"][0]["observed_step_ids"] = [steps[0]]
            obs["timestamps"][1]["observed_step_ids"] = steps[1:]
            obs["timestamps"][1]["artifact_ids"].remove(audio_id)
            row = run_audit(base, workspace, [obs])["candidate_results"][0]
            self.assertEqual(row["classification"], "EXATO")
            self.assertFalse(row["eligible_for_course"])
            self.assertIn(
                "audio_not_linked_to_all_required_steps",
                row["audio_access"]["review_failures"]["pt"],
            )

    def test_title_only_candidate_is_not_verifiable(self) -> None:
        temp, base, workspace, candidate, unit = self.scenario()
        with temp:
            result = run_audit(base, workspace, [])
            row = result["candidate_results"][0]
            self.assertEqual(row["classification"], "NAO_VERIFICAVEL")
            self.assertIn("internal_inspection_missing", row["failed_gates"])

    def test_missing_prerequisite_blocks_harder_equivalent(self) -> None:
        temp, base, workspace, candidate, unit = self.scenario()
        with temp:
            obs = observation(
                workspace,
                candidate,
                unit,
                match="EQUIVALENT",
                rationale="A estrutura e as decisões coincidem, mas a apresentação usa uma técnica avançada adicional.",
                missing_prerequisites=["Conhecer análise funcional"],
            )
            result = run_audit(base, workspace, [obs])
            self.assertEqual(result["candidate_results"][0]["classification"], "PARCIAL")

    def test_unverified_map_blocks_exact_classification(self) -> None:
        temp, base, workspace, candidate, unit = self.scenario()
        with temp:
            ledger = read_json(workspace / "ledgers" / "unit_ledger.json")
            ledger["map_state"] = "V0_HEURISTIC_DRAFT"
            atomic_write_json(workspace / "ledgers" / "unit_ledger.json", ledger)
            obs = observation(workspace, candidate, unit)
            result = run_audit(base, workspace, [obs])
            self.assertEqual(result["candidate_results"][0]["classification"], "NAO_VERIFICAVEL")

    def test_forbidden_classification_in_raw_evidence_is_rejected(self) -> None:
        temp, base, workspace, candidate, unit = self.scenario()
        with temp:
            obs = observation(workspace, candidate, unit)
            obs["classification"] = "EXATO"
            path = base / "bad-evidence.json"
            atomic_write_json(
                path,
                {
                    "schema_name": "projeto-e-video.evidence-input",
                    "schema_version": 1,
                    "observations": [obs],
                },
            )
            with self.assertRaisesRegex(ValueError, "autoaprovação"):
                audit(workspace, path)

    def test_forbidden_key_is_case_insensitive(self) -> None:
        temp, base, workspace, candidate, unit = self.scenario()
        with temp:
            obs = observation(workspace, candidate, unit)
            obs["Coverage Status"] = "complete"
            path = base / "bad-case-evidence.json"
            atomic_write_json(
                path,
                {
                    "schema_name": "projeto-e-video.evidence-input",
                    "schema_version": 1,
                    "observations": [obs],
                },
            )
            with self.assertRaisesRegex(ValueError, "autoaprovação"):
                audit(workspace, path)

    def test_unit_without_candidate_is_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            queries = read_json(workspace / "ledgers" / "search_queries.json")
            atomic_write_json(
                workspace / "ledgers" / "candidates.json",
                {
                    "schema_name": "projeto-e-video.candidates",
                    "schema_version": 2,
                    "created_at": "test",
                    "course_id": ledger["course_id"],
                    "search_scope": "GLOBAL_OPEN",
                    "search_attempts": [
                        {
                            "query_id": row["query_id"],
                            "status": "COMPLETED",
                            "result_count": 0,
                            "error": None,
                        }
                        for row in queries["queries"]
                    ],
                    "candidate_count": 0,
                    "candidates": [],
                },
            )
            atomic_write_json(
                workspace / "ledgers" / "audio_inventory.json",
                {
                    "schema_name": "projeto-e-video.audio-inventory",
                    "schema_version": 1,
                    "created_at": "test",
                    "course_id": ledger["course_id"],
                    "records": [],
                },
            )
            evidence = base / "empty.json"
            atomic_write_json(
                evidence,
                {
                    "schema_name": "projeto-e-video.evidence-input",
                    "schema_version": 2,
                    "observations": [],
                },
            )
            result = audit(workspace, evidence)
            self.assertEqual(result["unit_results"][0]["classification"], "NAO_ENCONTRADO")


if __name__ == "__main__":
    unittest.main()
