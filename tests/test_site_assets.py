import os
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))


class SiteAssetTests(unittest.TestCase):
    def test_podcast_library_reads_latest_and_previous_episode_sections(self) -> None:
        with open(os.path.join(ROOT, "docs", "assets", "js", "site.js"), encoding="utf-8") as f:
            script = f.read()

        self.assertIn('parsePodcastEpisodeSection("최신 에피소드")', script)
        self.assertIn('parsePodcastEpisodeSection("지난 에피소드")', script)

    def test_podcast_host_labels_match_current_hosts(self) -> None:
        with open(os.path.join(ROOT, "docs", "assets", "js", "site.js"), encoding="utf-8") as f:
            script = f.read()

        self.assertIn("재석 · 민아", script)
        self.assertNotIn("지윤 · 민종", script)


if __name__ == "__main__":
    unittest.main()
