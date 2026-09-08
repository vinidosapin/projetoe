from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from projeto_e_video.audio import import_audio_inventory
from projeto_e_video.collect import collect_evidence_assets
from projeto_e_video.util import atomic_write_json, read_json
from tests.helpers import add_candidate, verified_workspace


class CollectionTests(unittest.TestCase):
    def test_audio_segment_requires_track(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            add_candidate(base, workspace, ledger)
            with self.assertRaisesRegex(ValueError, "usados juntos"):
                collect_evidence_assets(workspace, "missing", audio_segments=[(1, 2)])

    def test_collects_hashed_audio_sample_from_selected_track(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            candidate = add_candidate(base, workspace, ledger)
            inventory = read_json(workspace / "ledgers" / "audio_inventory.json")
            inventory["records"][0]["tracks"][0]["formats"] = [
                {
                    "format_id": "251-pt",
                    "ext": "webm",
                    "abr": 128,
                    "audio_only": True,
                }
            ]
            inventory_file = base / "inventory-with-format.json"
            atomic_write_json(inventory_file, inventory)
            inventory = import_audio_inventory(workspace, inventory_file)
            track_id = inventory["records"][0]["tracks"][0]["track_id"]
            commands: list[list[str]] = []

            def fake_run(command: list[str], *, timeout: int) -> tuple[bool, str]:
                commands.append(command)
                if "-o" in command:
                    template = command[command.index("-o") + 1]
                    if "source_" in template and "%(ext)s" in template:
                        Path(template.replace("%(ext)s", "webm")).write_bytes(b"audio-source")
                if command and command[0] == "ffmpeg":
                    Path(command[-1]).write_bytes(b"RIFF-fake-wave")
                return True, "ok"

            with mock.patch(
                "projeto_e_video.collect.yt_dlp_command", return_value=["yt-dlp"]
            ), mock.patch(
                "projeto_e_video.collect.shutil.which", return_value="ffmpeg"
            ), mock.patch(
                "projeto_e_video.collect.validate_automated_video_url"
            ), mock.patch("projeto_e_video.collect._run", side_effect=fake_run):
                manifest = collect_evidence_assets(
                    workspace,
                    candidate["candidate_id"],
                    audio_track_id=track_id,
                    audio_segments=[(10, 20)],
                )
            self.assertEqual(manifest["audio_sample_count"], 1)
            audio = [row for row in manifest["artifacts"] if row["kind"] == "AUDIO"]
            self.assertEqual(len(audio), 1)
            self.assertEqual(len(audio[0]["sha256"]), 64)
            ffmpeg_audio = [
                command
                for command in commands
                if command and command[0] == "ffmpeg" and "-vn" in command
            ][0]
            self.assertIn("-t", ffmpeg_audio)
            self.assertEqual(ffmpeg_audio[ffmpeg_audio.index("-t") + 1], "10.000")
            self.assertNotIn("-to", ffmpeg_audio)
            self.assertFalse(any("--sub-langs" in command for command in commands))
            download = [
                command for command in commands if "--download-sections" in command
            ][0]
            self.assertEqual(
                download[download.index("--download-sections") + 1], "*10.000-20.000"
            )

    def test_subtitles_are_exact_and_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            candidate = add_candidate(base, workspace, ledger)
            commands: list[list[str]] = []

            def fake_run(command: list[str], *, timeout: int) -> tuple[bool, str]:
                commands.append(command)
                template = command[command.index("-o") + 1]
                Path(
                    template.replace("%(language)s", "pt-BR").replace(
                        "%(ext)s", "vtt"
                    )
                ).write_text("WEBVTT\n", encoding="utf-8")
                return True, "ok"

            with mock.patch(
                "projeto_e_video.collect.yt_dlp_command", return_value=["yt-dlp"]
            ), mock.patch(
                "projeto_e_video.collect.validate_automated_video_url"
            ), mock.patch("projeto_e_video.collect._run", side_effect=fake_run):
                manifest = collect_evidence_assets(
                    workspace,
                    candidate["candidate_id"],
                    subtitle_languages=["pt_BR", "en"],
                )
            command = commands[0]
            self.assertEqual(command[command.index("--sub-langs") + 1], "en,pt-BR")
            self.assertNotIn("--write-auto-subs", command)
            self.assertEqual(manifest["operation_status"]["subtitles"]["succeeded"], 1)

    def test_subtitle_failure_does_not_cancel_frame_collection(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace, ledger = verified_workspace(base)
            candidate = add_candidate(base, workspace, ledger)
            commands: list[list[str]] = []

            def fake_run(command: list[str], *, timeout: int) -> tuple[bool, str]:
                commands.append(command)
                if "--sub-langs" in command:
                    return False, "legenda indisponível"
                if "--download-sections" in command:
                    template = command[command.index("-o") + 1]
                    Path(template.replace("%(ext)s", "webm")).write_bytes(b"video")
                    return True, "ok"
                if command and command[0] == "ffmpeg":
                    Path(command[-1]).write_bytes(b"jpeg")
                    return True, "ok"
                return False, "inesperado"

            with mock.patch(
                "projeto_e_video.collect.yt_dlp_command", return_value=["yt-dlp"]
            ), mock.patch(
                "projeto_e_video.collect.shutil.which", return_value="ffmpeg"
            ), mock.patch(
                "projeto_e_video.collect.validate_automated_video_url"
            ), mock.patch("projeto_e_video.collect._run", side_effect=fake_run):
                manifest = collect_evidence_assets(
                    workspace,
                    candidate["candidate_id"],
                    frame_times=[30],
                    subtitle_languages=["pt"],
                )
            self.assertEqual(manifest["frame_count"], 1)
            self.assertEqual(manifest["operation_status"]["subtitles"]["succeeded"], 0)
            self.assertTrue(any(row.startswith("legendas:") for row in manifest["warnings"]))
            download = next(
                command for command in commands if "--download-sections" in command
            )
            selector = download[download.index("-f") + 1]
            self.assertTrue(
                selector.startswith("worstvideo[height<=480][protocol=https]/")
            )
            self.assertIn("/worstvideo[height<=480]/", selector)


if __name__ == "__main__":
    unittest.main()
