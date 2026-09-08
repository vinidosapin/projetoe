from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from projeto_e_video.external import preflight_report, run_command


class ExternalToolTests(unittest.TestCase):
    def test_preflight_reports_manual_fallback_without_installing_anything(self) -> None:
        def executable(name: str) -> str | None:
            return "/usr/bin/ffmpeg" if name == "ffmpeg" else None

        with mock.patch(
            "projeto_e_video.external.yt_dlp_command", return_value=None
        ), mock.patch(
            "projeto_e_video.external.shutil.which", side_effect=executable
        ):
            report = preflight_report()
        self.assertFalse(report["api_key_required"])
        self.assertTrue(report["manual_browser_flow_ready"])
        self.assertFalse(report["capabilities"]["automatic_public_search"])
        self.assertIn(".[automation]", report["tools"]["yt-dlp"]["install"])

    def test_timeout_becomes_operational_value_error(self) -> None:
        expired = subprocess.TimeoutExpired(["yt-dlp", "URL"], 1)
        with mock.patch("projeto_e_video.external.subprocess.run", side_effect=expired):
            with self.assertRaisesRegex(ValueError, "excedeu 1s"):
                run_command(["yt-dlp", "URL"], timeout_seconds=1)

    def test_shell_is_never_used(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["tool"], returncode=0, stdout=b"ok", stderr=b""
        )
        with mock.patch(
            "projeto_e_video.external.subprocess.run", return_value=completed
        ) as called:
            run_command(["tool", "literal;$HOME"], timeout_seconds=2)
        self.assertNotIn("shell", called.call_args.kwargs)
        self.assertEqual(called.call_args.args[0], ["tool", "literal;$HOME"])


if __name__ == "__main__":
    unittest.main()
