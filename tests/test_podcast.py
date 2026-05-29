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

    def test_recent_text_only_episode_is_not_considered_publishable_without_api_key(self) -> None:
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

        self.assertFalse(should_skip)

    def test_script_generation_failure_removes_unpublishable_current_episode(self) -> None:
        item = {
            "source": "rda",
            "title": "토마토 병 저항성 품종 개발",
            "published_at": "2026-05-28T09:00:00+09:00",
            "url": "https://example.com/tomato",
            "content_text": "토마토 병 저항성 품종 개발과 분자표지 선발 연구를 소개합니다.",
            "tags": ["토마토", "육종"],
        }
        bad_payload = {
            "releasedDate": "2026-05-29",
            "generation": {"scriptStatus": "fallback_script_error:Gemini HTTP 503", "audioStatus": "ok"},
            "audio": {"url": "2026-05-29.mp3"},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            podcast_dir = os.path.join(tmpdir, "podcast")
            os.mkdir(podcast_dir)
            with open(os.path.join(podcast_dir, "2026-05-29.json"), "w", encoding="utf-8") as f:
                json.dump(bad_payload, f)
            with open(os.path.join(podcast_dir, "2026-05-29.md"), "w", encoding="utf-8") as f:
                f.write("bad episode\n")
            with open(os.path.join(podcast_dir, "2026-05-29.mp3"), "wb") as f:
                f.write(b"bad audio")

            with (
                patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
                patch("collector.podcast._generate_script_with_gemini", side_effect=RuntimeError("Gemini HTTP 503")),
            ):
                res = podcast.build_podcast(
                    [item],
                    outdir=tmpdir,
                    now=datetime(2026, 5, 29, 12, 0, tzinfo=ZoneInfo("Asia/Seoul")),
                    force=True,
                )

            self.assertEqual(res["status"], "script_generation_failed")
            self.assertFalse(os.path.exists(os.path.join(podcast_dir, "2026-05-29.json")))
            self.assertFalse(os.path.exists(os.path.join(podcast_dir, "2026-05-29.md")))
            self.assertFalse(os.path.exists(os.path.join(podcast_dir, "2026-05-29.mp3")))

    def test_successful_generation_returns_ok_and_writes_publishable_episode(self) -> None:
        item = {
            "source": "rda",
            "title": "토마토 병 저항성 품종 개발",
            "published_at": "2026-05-28T09:00:00+09:00",
            "url": "https://example.com/tomato",
            "content_text": "토마토 병 저항성 품종 개발과 분자표지 선발 연구를 소개합니다.",
            "tags": ["토마토", "육종"],
        }
        line_text = (
            "토마토 병 저항성 품종 개발은 유전체 정보와 분자표지 선발을 함께 활용해 현장 피해를 줄이는 흐름을 보여줍니다. "
            "연구 단계의 예측 결과가 실제 품종 선발, 검역, 재배 관리와 연결될 때 농가가 체감하는 피해 저감 효과도 커집니다. "
        )
        episode = {
            "title": "토마토 육종 브리핑",
            "shortDescription": "토마토 병 저항성 품종 개발 흐름을 다룹니다.",
            "selectedItems": [{"idx": 1, "reason": "토마토 병 저항성 육종 사례"}],
            "dialogue": [
                {
                    "speaker": podcast.HOST_LEAD if i % 2 == 0 else podcast.HOST_EXPERT,
                    "text": f"{line_text}이 대목은 {i + 1}번째 관점에서 연구 의미와 농가 적용 가능성을 설명합니다.",
                }
                for i in range(10)
            ],
        }

        def fake_audio(episode: dict, *, podcast_dir: str, release_date: str, api_key: str, model: str, keep_wav: bool) -> dict:
            path = os.path.join(podcast_dir, f"{release_date}.mp3")
            with open(path, "wb") as f:
                f.write(b"audio")
            return {"url": f"{release_date}.mp3", "mimeType": "audio/mpeg", "durationSeconds": 10, "bytes": 5}

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
                patch("collector.podcast._generate_script_with_gemini", return_value=episode),
                patch("collector.podcast._synthesize_episode_audio", side_effect=fake_audio),
            ):
                res = podcast.build_podcast(
                    [item],
                    outdir=tmpdir,
                    now=datetime(2026, 5, 29, 12, 0, tzinfo=ZoneInfo("Asia/Seoul")),
                    force=True,
                )

            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["script"], "ok")
            self.assertEqual(res["audio_file"], "2026-05-29.mp3")
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "podcast", "latest.json")))

    def test_repetitive_script_fails_quality_gate(self) -> None:
        episode = {
            "title": "반복 대본",
            "shortDescription": "반복 대본",
            "selectedItems": [{"idx": 1, "reason": "중요 기사"}],
            "dialogue": [
                {"speaker": podcast.HOST_LEAD if i % 2 == 0 else podcast.HOST_EXPERT, "text": "같은 설명입니다."}
                for i in range(10)
            ],
        }

        issues = podcast._episode_quality_issues(episode)

        self.assertIn("dialogue contains excessive repetition", issues)

    def test_script_api_retries_transient_503(self) -> None:
        class FakeResponse:
            def __init__(self, status_code: int, text: str, payload: dict | None = None) -> None:
                self.status_code = status_code
                self.text = text
                self.headers = {}
                self._payload = payload or {}

            def json(self) -> dict:
                return self._payload

        responses = [
            FakeResponse(503, '{"error":{"status":"UNAVAILABLE"}}'),
            FakeResponse(200, "{}", {"candidates": [{"content": {"parts": [{"text": "{\"ok\": true}"}]}}]}),
        ]

        with (
            patch("requests.post", side_effect=responses) as post,
            patch("collector.podcast._sleep_before_retry") as sleep,
        ):
            text = podcast._call_gemini_jsonish(
                "prompt",
                api_key="test-key",
                model=podcast.DEFAULT_SCRIPT_MODEL,
                schema={"type": "object"},
                max_tokens=64,
            )

        self.assertEqual(text, "{\"ok\": true}")
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
