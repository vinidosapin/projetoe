from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from projeto_e_video.audio import inspect_candidate_audio, validate_audio_inventory
from projeto_e_video.languages import global_seed_languages, normalize_language_tag
from projeto_e_video.util import read_json
from tests.helpers import add_candidate, observation, run_audit, verified_workspace


class AudioTests(unittest.TestCase):
    def test_language_tags_and_global_seed_are_explicit(self) -> None:
        self.assertEqual(normalize_language_tag("pt_br"), "pt-BR")
        self.assertEqual(normalize_language_tag("zh-hans"), "zh-Hans")
        seeds = global_seed_languages()
        self.assertEqual(seeds[:2], ["pt", "en"])
        self.assertGreaterEqual(len(seeds), 30)

    def test_track_metadata_alone_never_releases_video(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            candidate = add_candidate(base, workspace, ledger)
            unit = ledger["units"][0]
            result = run_audit(
                base,
                workspace,
                [observation(workspace, candidate, unit, with_audio_review=False)],
            )["candidate_results"][0]
            self.assertEqual(result["classification"], "EXATO")
            self.assertFalse(result["eligible_for_course"])
            self.assertEqual(result["audio_access"]["target_statuses"]["pt"], "TRACK_METADATA_ONLY")
            self.assertEqual(result["useful_seconds"], 0)
            self.assertEqual(result["content_useful_seconds"], 80)

    def test_subtitle_only_never_counts_as_dubbing(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            candidate = add_candidate(
                base,
                workspace,
                ledger,
                include_audio_track=False,
                subtitle_language="pt-BR",
            )
            unit = ledger["units"][0]
            result = run_audit(
                base,
                workspace,
                [observation(workspace, candidate, unit, with_audio_review=False)],
            )["candidate_results"][0]
            self.assertEqual(result["audio_access"]["target_statuses"]["pt"], "SUBTITLE_ONLY")
            self.assertFalse(result["eligible_for_course"])

    def test_automatic_dub_can_pass_only_after_full_review(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            candidate = add_candidate(
                base, workspace, ledger, audio_kind="DUB_AUTOMATIC"
            )
            unit = ledger["units"][0]
            valid = observation(
                workspace,
                candidate,
                unit,
                audio_access_type="DUB_AUTOMATIC",
            )
            result = run_audit(base, workspace, [valid])["candidate_results"][0]
            self.assertTrue(result["eligible_for_course"])
            self.assertEqual(
                result["audio_access"]["target_statuses"]["pt"],
                "DUB_AUTOMATIC_PT",
            )

            invalid = observation(
                workspace,
                candidate,
                unit,
                audio_access_type="DUB_AUTOMATIC",
                audio_issues=["A tradução troca o nome de uma variável."],
            )
            result = run_audit(base, workspace, [invalid])["candidate_results"][0]
            self.assertFalse(result["eligible_for_course"])
            self.assertEqual(
                result["audio_access"]["target_statuses"]["pt"],
                "NAO_VERIFICAVEL",
            )

    def test_metadata_kind_conflict_blocks_audio(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            candidate = add_candidate(
                base, workspace, ledger, audio_kind="DUB_AUTOMATIC"
            )
            unit = ledger["units"][0]
            raw = observation(workspace, candidate, unit, audio_access_type="ORIGINAL")
            result = run_audit(base, workspace, [raw])["candidate_results"][0]
            self.assertFalse(result["eligible_for_course"])
            self.assertIn(
                "metadata_kind_conflict",
                result["audio_access"]["review_failures"]["pt"],
            )

    def test_direct_playback_requires_selected_track_capture(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            candidate = add_candidate(base, workspace, ledger)
            unit = ledger["units"][0]
            raw = observation(
                workspace,
                candidate,
                unit,
                methods=["FALA_VERIFICADA", "FRAME"],
            )
            review = raw["audio_reviews"][0]
            frame_id = raw["artifacts"][1]["artifact_id"]
            review.update(
                {
                    "verification_method": "DIRECT_PLAYBACK",
                    "audio_artifact_ids": [],
                    "track_selection_artifact_id": frame_id,
                    "direct_playback_observed": True,
                }
            )
            result = run_audit(base, workspace, [raw])["candidate_results"][0]
            self.assertTrue(result["eligible_for_course"])

            review["track_selection_artifact_id"] = None
            with self.assertRaisesRegex(ValueError, "DIRECT_PLAYBACK"):
                run_audit(base, workspace, [raw])

    def test_yt_dlp_inventory_keeps_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            candidate = add_candidate(base, workspace, ledger)
            payload = {
                "formats": [
                    {
                        "format_id": "251-pt",
                        "acodec": "opus",
                        "vcodec": "none",
                        "language": "pt-BR",
                        "format_note": "medium, dubbed-auto",
                        "abr": 128,
                        "ext": "webm",
                    },
                    {
                        "format_id": "251-en",
                        "acodec": "opus",
                        "vcodec": "none",
                        "language": "en-US",
                        "format_note": "medium, original",
                        "abr": 128,
                        "ext": "webm",
                    },
                    {
                        "format_id": "250-pt",
                        "acodec": "opus",
                        "vcodec": "none",
                        "language": "pt-BR",
                        "format_note": "low, dubbed-auto",
                        "abr": 64,
                        "ext": "webm",
                    },
                    {
                        "format_id": "251-commentary",
                        "acodec": "opus",
                        "vcodec": "none",
                        "language": "pt-BR",
                        "format_note": "Portuguese commentary, dubbed-auto",
                        "abr": 96,
                        "ext": "webm",
                    },
                ],
                "subtitles": {"pt-BR": [{"ext": "vtt"}]},
                "automatic_captions": {
                    "en": [{"ext": "vtt"}],
                    "es": [{"ext": "vtt"}],
                    "ja": [{"ext": "vtt"}],
                },
            }
            completed = subprocess.CompletedProcess(
                args=["yt-dlp"], returncode=0, stdout=json.dumps(payload).encode(), stderr=b""
            )
            with mock.patch("projeto_e_video.audio.yt_dlp_command", return_value=["yt-dlp"]), mock.patch(
                "projeto_e_video.audio.run_command", return_value=completed
            ), mock.patch(
                "projeto_e_video.audio.validate_automated_video_url"
            ):
                record = inspect_candidate_audio(workspace, candidate["candidate_id"])
            by_language = {row["language_family"]: row for row in record["tracks"]}
            self.assertEqual(
                len([row for row in record["tracks"] if row["language_family"] == "pt"]),
                2,
            )
            self.assertIn(
                2,
                [
                    len(row["formats"])
                    for row in record["tracks"]
                    if row["language_family"] == "pt"
                ],
            )
            self.assertEqual(by_language["pt"]["audio_kind_hint"], "DUB_AUTOMATIC")
            self.assertEqual(by_language["en"]["audio_kind_hint"], "ORIGINAL")
            self.assertTrue(all(row["metadata_only"] for row in record["tracks"]))
            self.assertEqual(
                {row["language_family"] for row in record["subtitles"]},
                {"pt", "en"},
            )
            document = read_json(workspace / "ledgers" / "audio_inventory.json")
            self.assertEqual(
                validate_audio_inventory(
                    document, read_json(workspace / "ledgers" / "candidates.json")
                )["records"],
                document["records"],
            )

    def test_provider_private_language_suffix_does_not_abort_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            candidate = add_candidate(base, workspace, ledger)
            payload = {
                "formats": [
                    {
                        "format_id": "251",
                        "acodec": "opus",
                        "vcodec": "none",
                        "language": "en-j3PyPqV-e1s",
                        "format_note": "original",
                        "ext": "webm",
                    }
                ],
                "subtitles": {
                    "en-j3PyPqV-e1s": [{"ext": "vtt"}],
                },
            }
            completed = subprocess.CompletedProcess(
                args=["yt-dlp"],
                returncode=0,
                stdout=json.dumps(payload).encode(),
                stderr=b"",
            )
            with mock.patch(
                "projeto_e_video.audio.yt_dlp_command", return_value=["yt-dlp"]
            ), mock.patch(
                "projeto_e_video.audio.run_command", return_value=completed
            ), mock.patch("projeto_e_video.audio.validate_automated_video_url"):
                record = inspect_candidate_audio(workspace, candidate["candidate_id"])
            self.assertEqual(record["tracks"][0]["language"], "en")
            self.assertEqual(
                record["tracks"][0]["provider_language_tag"],
                "en-j3PyPqV-e1s",
            )
            self.assertTrue(record["tracks"][0]["normalization_warning"])
            self.assertTrue(record["warnings"])


if __name__ == "__main__":
    unittest.main()
