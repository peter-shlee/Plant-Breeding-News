import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from collector import podcast


class PodcastAudioTests(unittest.TestCase):
    def test_synthesize_audio_falls_back_to_single_line_tts(self) -> None:
        episode = {
            "dialogue": [
                {"speaker": podcast.HOST_LEAD, "text": "안녕하세요. 식물 육종 뉴스입니다."},
                {"speaker": podcast.HOST_EXPERT, "text": "오늘은 유전체 선발 소식을 짚어보겠습니다."},
            ]
        }
        line_pcm = b"\x01\x00" * 2400

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("collector.podcast._call_gemini_tts", side_effect=RuntimeError("Gemini TTS HTTP 500")),
                patch("collector.podcast._call_gemini_tts_voice", return_value=line_pcm) as voice_tts,
                patch("collector.podcast.shutil.which", return_value=None),
            ):
                meta = podcast._synthesize_episode_audio(
                    episode,
                    podcast_dir=tmpdir,
                    release_date="2026-05-29",
                    api_key="test-key",
                    model=podcast.DEFAULT_TTS_MODEL,
                    keep_wav=False,
                )

        self.assertEqual(meta["url"], "2026-05-29.wav")
        self.assertEqual(meta["mimeType"], "audio/wav")
        self.assertEqual(meta["synthesisMode"], "single_speaker_fallback")
        self.assertIn("Gemini TTS HTTP 500", meta["fallbackReason"])
        self.assertEqual(voice_tts.call_count, 2)
        self.assertGreater(meta["bytes"], len(line_pcm) * 2)

    def test_synthesize_audio_falls_back_to_secondary_tts_model(self) -> None:
        episode = {
            "dialogue": [
                {"speaker": podcast.HOST_LEAD, "text": "안녕하세요. 식물 육종 뉴스입니다."},
            ]
        }
        line_pcm = b"\x02\x00" * 2400
        primary = podcast.DEFAULT_TTS_MODEL
        secondary = podcast.DEFAULT_TTS_FALLBACK_MODELS[0]

        def fake_voice_tts(text: str, *, api_key: str, model: str, voice_name: str) -> bytes:
            if model == primary:
                raise RuntimeError("Gemini TTS HTTP 500")
            return line_pcm

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("collector.podcast._call_gemini_tts", side_effect=RuntimeError("Gemini TTS HTTP 500")),
                patch("collector.podcast._call_gemini_tts_voice", side_effect=fake_voice_tts),
                patch("collector.podcast.shutil.which", return_value=None),
            ):
                meta = podcast._synthesize_episode_audio(
                    episode,
                    podcast_dir=tmpdir,
                    release_date="2026-05-29",
                    api_key="test-key",
                    model=primary,
                    keep_wav=False,
                )

        self.assertEqual(meta["ttsModel"], secondary)
        self.assertEqual(meta["primaryTtsModel"], primary)
        self.assertIn("Gemini TTS HTTP 500", meta["modelFallbackReason"])

    def test_recent_text_only_episode_retries_when_api_key_is_available(self) -> None:
        payload = {
            "releasedDate": "2026-05-29",
            "generation": {"audioStatus": "tts_error:Gemini TTS HTTP 500"},
            "audio": {},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            podcast_dir = os.path.join(tmpdir, "podcast")
            os.mkdir(podcast_dir)
            with open(os.path.join(podcast_dir, "latest.json"), "w", encoding="utf-8") as f:
                json.dump(payload, f)

            should_skip = podcast._has_recent_episode(
                podcast_dir=podcast_dir,
                now_kst=datetime(2026, 5, 29, 12, 0, tzinfo=ZoneInfo("Asia/Seoul")),
                min_days_between=6,
                api_key_present=True,
                skip_audio=False,
            )

        self.assertFalse(should_skip)

    def test_recent_text_only_episode_skips_without_api_key(self) -> None:
        payload = {
            "releasedDate": "2026-05-29",
            "generation": {"audioStatus": "skipped_no_api_key"},
            "audio": {},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            podcast_dir = os.path.join(tmpdir, "podcast")
            os.mkdir(podcast_dir)
            with open(os.path.join(podcast_dir, "latest.json"), "w", encoding="utf-8") as f:
                json.dump(payload, f)

            should_skip = podcast._has_recent_episode(
                podcast_dir=podcast_dir,
                now_kst=datetime(2026, 5, 29, 12, 0, tzinfo=ZoneInfo("Asia/Seoul")),
                min_days_between=6,
                api_key_present=False,
                skip_audio=False,
            )

        self.assertTrue(should_skip)


if __name__ == "__main__":
    unittest.main()
