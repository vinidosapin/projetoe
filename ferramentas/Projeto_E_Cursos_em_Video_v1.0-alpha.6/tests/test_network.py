from __future__ import annotations

import unittest
from unittest import mock

from projeto_e_video.network import (
    validate_automated_video_url,
    validate_http_url,
    validate_public_network_url,
)


class NetworkTests(unittest.TestCase):
    def test_private_literal_and_credentials_are_rejected_without_network(self) -> None:
        with self.assertRaisesRegex(ValueError, "privada"):
            validate_http_url("http" + "://127.0.0.1/video", resolve=False)
        with self.assertRaisesRegex(ValueError, "credenciais"):
            validate_http_url("https" + "://user:pass@example.com/video", resolve=False)

    def test_all_resolved_addresses_must_be_public(self) -> None:
        with mock.patch(
            "projeto_e_video.network.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("10.0.0.8", 443))],
        ):
            with self.assertRaisesRegex(ValueError, "privada"):
                validate_public_network_url("https" + "://example.com/video")

    def test_automated_collection_uses_known_public_platforms(self) -> None:
        public = [(2, 1, 6, "", ("8.8.8.8", 443))]
        with mock.patch(
            "projeto_e_video.network.socket.getaddrinfo", return_value=public
        ):
            validate_automated_video_url(
                "https" + "://www.youtube.com/watch?v=abcdefghijk"
            )
            with self.assertRaisesRegex(ValueError, "plataformas públicas"):
                validate_automated_video_url("https" + "://example.com/video")


if __name__ == "__main__":
    unittest.main()
