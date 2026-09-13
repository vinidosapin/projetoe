import unittest
from projeto_e_video.providers import _candidate_from_raw

class TotalAllowlistV047Test(unittest.TestCase):
    def test_external_site_candidate_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "somente vídeos diretos do YouTube"):
            _candidate_from_raw({"unit_ids":["U1"],"url":"https" + "://example.com/a","title":"x","channel":"Brasil Escola Oficial"},{"U1"})
    def test_fourth_youtube_channel_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "fora da allowlist"):
            _candidate_from_raw({"unit_ids":["U1"],"url":"https" + "://www.youtube.com/watch?v=abcdefghijk","title":"x","channel":"Outro Canal"},{"U1"})
    def test_two_videos_from_same_approved_channel_are_individually_accepted(self):
        a=_candidate_from_raw({"unit_ids":["U1"],"url":"https" + "://www.youtube.com/watch?v=abcdefghijk","title":"a","channel":"Brasil Escola Oficial"},{"U1"})
        b=_candidate_from_raw({"unit_ids":["U1"],"url":"https" + "://www.youtube.com/watch?v=lmnopqrstuv","title":"b","channel":"Brasil Escola Oficial"},{"U1"})
        self.assertEqual(a["channel"], b["channel"])
        self.assertNotEqual(a["url"], b["url"])

if __name__ == "__main__": unittest.main()
