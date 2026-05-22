from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import time
import wave
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import format_datetime
from typing import Any, Iterable, Optional
from xml.sax.saxutils import escape

from dateutil import parser

from .sitegen import item_relpath


DEFAULT_SCRIPT_MODEL = "gemini-3.5-flash"
DEFAULT_TTS_MODEL = "gemini-3.1-flash-tts-preview"
DEFAULT_SITE_URL = "https://peter-shlee.github.io/Plant-Breeding-News"
PODCAST_DIRNAME = "podcast"


@dataclass(frozen=True)
class PodcastCandidate:
    idx: int
    date: str
    source: str
    title: str
    item_path: str
    original_url: str
    excerpt: str
    tags: tuple[str, ...]
    score: float


def build_podcast(
    items: Iterable[dict[str, Any]],
    *,
    outdir: str,
    days: int = 7,
    max_candidates: int = 24,
    target_minutes: int = 5,
    script_model: str = DEFAULT_SCRIPT_MODEL,
    tts_model: str = DEFAULT_TTS_MODEL,
    site_url: str = DEFAULT_SITE_URL,
    min_days_between: int = 6,
    force: bool = False,
    skip_audio: bool = False,
    keep_wav: bool = False,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build a static podcast episode under docs/podcast.

    The command is intentionally safe for scheduled CI:
    - If no Gemini key is present, it writes a deterministic text-only episode.
    - If a recent episode already exists, it skips generation unless forced.
    - If TTS or ffmpeg fails, it keeps metadata/script generation successful.
    """

    now_kst = _kst_now(now)
    release_date = now_kst.date().isoformat()
    podcast_dir = os.path.join(outdir, PODCAST_DIRNAME)
    os.makedirs(podcast_dir, exist_ok=True)

    if not force and _has_recent_episode(podcast_dir=podcast_dir, now_kst=now_kst, min_days_between=min_days_between):
        index_path = _write_index(podcast_dir=podcast_dir, site_url=site_url)
        feed_path = _write_feed(podcast_dir=podcast_dir, site_url=site_url)
        return {
            "status": "skipped_recent_episode",
            "podcast_dir": os.path.relpath(podcast_dir, outdir),
            "index": os.path.relpath(index_path, outdir),
            "feed": os.path.relpath(feed_path, outdir),
        }

    candidates = _select_candidates(items, days=days, max_candidates=max_candidates, now=now_kst)
    if not candidates:
        index_path = _write_index(podcast_dir=podcast_dir, site_url=site_url)
        feed_path = _write_feed(podcast_dir=podcast_dir, site_url=site_url)
        return {
            "status": "no_items",
            "podcast_dir": os.path.relpath(podcast_dir, outdir),
            "index": os.path.relpath(index_path, outdir),
            "feed": os.path.relpath(feed_path, outdir),
        }

    range_start = (now_kst - timedelta(days=days)).date().isoformat()
    range_end = release_date

    api_key = os.getenv("GEMINI_API_KEY") or ""
    script_status = "fallback_no_api_key"
    if api_key:
        try:
            episode = _generate_script_with_gemini(
                candidates,
                range_start=range_start,
                range_end=range_end,
                target_minutes=target_minutes,
                api_key=api_key,
                model=script_model,
            )
            script_status = "ok"
        except Exception as e:
            episode = _fallback_episode(candidates, range_start=range_start, range_end=range_end)
            script_status = f"fallback_script_error:{e}"
    else:
        episode = _fallback_episode(candidates, range_start=range_start, range_end=range_end)

    episode = _normalize_episode(episode, candidates=candidates, range_start=range_start, range_end=range_end)

    audio_meta: dict[str, Any] = {}
    audio_status = "skipped"
    if not skip_audio and api_key:
        try:
            audio_meta = _synthesize_episode_audio(
                episode,
                podcast_dir=podcast_dir,
                release_date=release_date,
                api_key=api_key,
                model=tts_model,
                keep_wav=keep_wav,
            )
            audio_status = "ok" if audio_meta else "empty_audio"
        except Exception as e:
            audio_status = f"tts_error:{e}"
    elif not api_key:
        audio_status = "skipped_no_api_key"

    dated_json = os.path.join(podcast_dir, f"{release_date}.json")
    latest_json = os.path.join(podcast_dir, "latest.json")
    dated_md = os.path.join(podcast_dir, f"{release_date}.md")

    preserved_existing_audio = False
    if not audio_meta:
        existing_payload = _load_existing_audio_payload(podcast_dir=podcast_dir, release_date=release_date)
        if existing_payload:
            payload = existing_payload
            preserved_existing_audio = True
            audio_status = f"{audio_status}_preserved_existing_audio"
        else:
            payload = _episode_payload(
                episode,
                candidates=candidates,
                release_date=release_date,
                range_start=range_start,
                range_end=range_end,
                script_model=script_model,
                tts_model=tts_model,
                audio_meta=audio_meta,
            )
    else:
        payload = _episode_payload(
            episode,
            candidates=candidates,
            release_date=release_date,
            range_start=range_start,
            range_end=range_end,
            script_model=script_model,
            tts_model=tts_model,
            audio_meta=audio_meta,
        )

    _write_json(dated_json, payload)
    _write_json(latest_json, payload)
    _write_episode_md(dated_md, payload)
    index_path = _write_index(podcast_dir=podcast_dir, site_url=site_url)
    feed_path = _write_feed(podcast_dir=podcast_dir, site_url=site_url)

    return {
        "status": "ok",
        "script": script_status,
        "audio": audio_status,
        "items": len(candidates),
        "episode": os.path.relpath(dated_json, outdir),
        "latest": os.path.relpath(latest_json, outdir),
        "page": os.path.relpath(dated_md, outdir),
        "index": os.path.relpath(index_path, outdir),
        "feed": os.path.relpath(feed_path, outdir),
        "audio_file": (payload.get("audio") or {}).get("url", ""),
        "preserved_existing_audio": preserved_existing_audio,
    }


def _kst_now(now: Optional[datetime] = None) -> datetime:
    from zoneinfo import ZoneInfo

    base = now or datetime.now().astimezone()
    return base.astimezone(ZoneInfo("Asia/Seoul"))


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return parser.isoparse(s)
    except Exception:
        try:
            return parser.parse(s, fuzzy=True)
        except Exception:
            return None


def _to_tz(dt: datetime, tzinfo: Any) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tzinfo)
    return dt.astimezone(tzinfo)


def _date_ymd(it: dict[str, Any]) -> str:
    return (it.get("published_at") or it.get("fetched_at") or "").split("T")[0]


def _norm_title(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _excerpt(it: dict[str, Any], *, max_chars: int = 700) -> str:
    summary = (it.get("summary") or "").strip()
    text = summary or (it.get("content_text") or "").strip()
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


def _select_candidates(
    items: Iterable[dict[str, Any]],
    *,
    days: int,
    max_candidates: int,
    now: datetime,
) -> list[PodcastCandidate]:
    cutoff = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)

    by_title: dict[str, dict[str, Any]] = {}
    for it in items:
        dt = _parse_dt(it.get("published_at")) or _parse_dt(it.get("fetched_at"))
        if dt is not None:
            dt_kst = _to_tz(dt, now.tzinfo)
            if dt_kst < cutoff:
                continue

        title = (it.get("title") or "").strip()
        if not title:
            continue

        key = _norm_title(title)
        prev = by_title.get(key)
        if prev is None:
            by_title[key] = it
            continue
        # Prefer richer excerpts, then source pages with original content.
        if len(_excerpt(it)) > len(_excerpt(prev)):
            by_title[key] = it

    scored: list[tuple[float, datetime, dict[str, Any]]] = []
    for it in by_title.values():
        parsed_dt = _parse_dt(it.get("published_at")) or _parse_dt(it.get("fetched_at"))
        dt = _to_tz(parsed_dt, now.tzinfo) if parsed_dt else datetime.min.replace(tzinfo=now.tzinfo)
        scored.append((_score_item(it), dt, it))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

    candidates: list[PodcastCandidate] = []
    for score, _dt, it in scored[: max(1, max_candidates)]:
        candidates.append(
            PodcastCandidate(
                idx=len(candidates) + 1,
                date=_date_ymd(it),
                source=(it.get("source") or "unknown").strip(),
                title=(it.get("title") or "").strip(),
                item_path=item_relpath(it).replace(os.sep, "/"),
                original_url=(it.get("url") or "").strip(),
                excerpt=_excerpt(it),
                tags=tuple(it.get("tags") or []),
                score=round(score, 2),
            )
        )
    return candidates


_CORE_KWS = [
    "육종",
    "품종",
    "신품종",
    "종자",
    "계통",
    "교배",
    "유전체",
    "전사체",
    "표현체",
    "마커",
    "snp",
    "kasp",
    "qtl",
    "gwas",
    "내병성",
    "저항성",
    "유전자편집",
    "crispr",
    "품종보호",
    "upov",
    "plant breeding",
    "breeding",
    "cultivar",
    "variety",
    "seed",
    "germplasm",
    "genomics",
    "phenotyping",
    "marker",
    "gene editing",
    "speed breeding",
]

_SECONDARY_KWS = [
    "작물",
    "벼",
    "쌀",
    "밀",
    "보리",
    "콩",
    "옥수수",
    "감자",
    "토마토",
    "고추",
    "감귤",
    "양파",
    "딸기",
    "과수",
    "원예",
    "crop",
    "rice",
    "wheat",
    "barley",
    "soybean",
    "corn",
    "maize",
    "potato",
    "tomato",
    "citrus",
]

_PENALTY_KWS = [
    "채용",
    "모집",
    "입찰",
    "공고",
    "행사",
    "회의",
    "위원회",
    "업무협약",
    "mou",
    "교육",
    "어린이",
]


def _score_item(it: dict[str, Any]) -> float:
    text = " ".join(
        [
            it.get("title") or "",
            it.get("summary") or "",
            it.get("content_text") or "",
            " ".join(it.get("tags") or []),
        ]
    )
    t = re.sub(r"\s+", " ", text.lower()).strip()
    score = 0.0
    score += _hit_count(t, _CORE_KWS) * 2.0
    score += _hit_count(t, _SECONDARY_KWS) * 0.75
    score -= _hit_count(t, _PENALTY_KWS) * 0.8
    if (it.get("source") or "") == "seedworld":
        score += 0.3
    if it.get("summary"):
        score += 0.25
    return score


def _hit_count(norm_text: str, keywords: list[str]) -> int:
    hits = 0
    for kw in keywords:
        k = kw.lower()
        if re.fullmatch(r"[a-z0-9 ]+", k):
            pat = r"\b" + re.escape(k).replace(r"\ ", r"\s+") + r"\b"
            if re.search(pat, norm_text):
                hits += 1
        elif k in norm_text:
            hits += 1
    return hits


def _generate_script_with_gemini(
    candidates: list[PodcastCandidate],
    *,
    range_start: str,
    range_end: str,
    target_minutes: int,
    api_key: str,
    model: str,
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "shortDescription": {"type": "string"},
            "selectedItems": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "idx": {"type": "integer"},
                        "reason": {"type": "string"},
                    },
                    "required": ["idx", "reason"],
                },
            },
            "dialogue": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "speaker": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["speaker", "text"],
                },
            },
        },
        "required": ["title", "shortDescription", "selectedItems", "dialogue"],
    }

    prompt = _script_prompt(candidates, range_start=range_start, range_end=range_end, target_minutes=target_minutes)
    text = _call_gemini_jsonish(prompt, api_key=api_key, model=model, schema=schema, max_tokens=4200)
    try:
        return json.loads(_strip_json_fence(text))
    except Exception as e:
        raise RuntimeError(f"failed to parse script JSON: {e}: {text[:300]}")


def _script_prompt(
    candidates: list[PodcastCandidate],
    *,
    range_start: str,
    range_end: str,
    target_minutes: int,
) -> str:
    lines: list[str] = []
    lines.append("너는 '식물 육종 뉴스'의 AI 팟캐스트 프로듀서다.")
    lines.append("아래 제공된 기사 후보만 근거로 한국어 2인 진행 팟캐스트 대본을 작성하라.")
    lines.append("")
    lines.append("[진행자]")
    lines.append("- 지윤: 따뜻하고 명료한 진행자. 청취자에게 맥락을 열어준다.")
    lines.append("- 민종: 식물유전학/육종 전문가. QTL, 마커, CRISPR, 유전체, 품종보호 등 기술 맥락을 정확히 설명한다.")
    lines.append("")
    lines.append("[규칙]")
    lines.append(f"- 기간: {range_start} ~ {range_end}")
    lines.append("- selectedItems는 아래 후보의 idx 중 중요한 5~7개만 고른다.")
    lines.append("- 제공되지 않은 기사, 통계, 링크, 인물 발언은 만들지 않는다.")
    lines.append("- 전문용어는 정확하게 쓰되, 개인 청취자가 이해할 수 있게 한 문장 안에서 풀어준다.")
    lines.append(f"- 대본은 약 {target_minutes}분 분량으로, 8~12턴의 자연스러운 대화로 작성한다.")
    lines.append("- 모든 대사는 한국어로 작성한다. 외국어 제목은 필요한 경우 한국어로 풀어 말한다.")
    lines.append("- speaker 값은 반드시 '지윤' 또는 '민종'만 사용한다.")
    lines.append("- JSON 객체만 출력한다. 코드블록 금지.")
    lines.append("")
    lines.append("[기사 후보]")
    for c in candidates:
        tags = ", ".join(c.tags) if c.tags else "-"
        lines.append(f"idx={c.idx} | date={c.date} | source={c.source} | score={c.score:g}")
        lines.append(f"title: {c.title}")
        lines.append(f"url: {c.original_url}")
        lines.append(f"tags: {tags}")
        lines.append(f"excerpt: {c.excerpt or '(본문 발췌 없음)'}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _call_gemini_jsonish(
    prompt: str,
    *,
    api_key: str,
    model: str,
    schema: dict[str, Any],
    max_tokens: int,
    timeout_s: int = 90,
) -> str:
    import requests

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.45,
            "maxOutputTokens": max_tokens,
            "responseFormat": {
                "text": {
                    "mimeType": "application/json",
                    "schema": schema,
                }
            },
        },
    }

    r = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:500]}")
    data = r.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        raise RuntimeError(f"Gemini response missing text: {json.dumps(data, ensure_ascii=False)[:500]}")


def _strip_json_fence(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _fallback_episode(candidates: list[PodcastCandidate], *, range_start: str, range_end: str) -> dict[str, Any]:
    selected = candidates[:6]
    title = f"식물 육종 뉴스 팟캐스트 ({range_end})"
    short = "이번 주 식물 육종·종자·품종 관련 핵심 소식을 요약했다."

    dialogue: list[dict[str, str]] = [
        {
            "speaker": "지윤",
            "text": f"안녕하세요. 식물 육종 뉴스입니다. 오늘은 {range_start}부터 {range_end}까지 들어온 소식 중 눈에 띄는 흐름을 짚어보겠습니다.",
        },
        {
            "speaker": "민종",
            "text": "이번 주는 품종 개발, 종자 산업, 유전체 기술, 현장 적용 이슈를 함께 보면 좋겠습니다.",
        },
    ]
    for c in selected:
        dialogue.append(
            {
                "speaker": "지윤",
                "text": f"먼저 {c.source} 소식입니다. {c.title}",
            }
        )
        detail = c.excerpt or "본문 발췌는 없지만, 육종과 종자 산업 관점에서 확인할 만한 주제입니다."
        if len(detail) > 180:
            detail = detail[:179].rstrip() + "…"
        dialogue.append(
            {
                "speaker": "민종",
                "text": detail,
            }
        )
    dialogue.append(
        {
            "speaker": "지윤",
            "text": "오늘 준비한 소식은 여기까지입니다. 원문 링크와 대본은 팟캐스트 페이지에서 확인하실 수 있습니다.",
        }
    )

    return {
        "title": title,
        "shortDescription": short,
        "selectedItems": [{"idx": c.idx, "reason": "키워드 점수와 최신성을 기준으로 선택"} for c in selected],
        "dialogue": dialogue,
    }


def _normalize_episode(
    episode: dict[str, Any],
    *,
    candidates: list[PodcastCandidate],
    range_start: str,
    range_end: str,
) -> dict[str, Any]:
    if not isinstance(episode, dict):
        episode = {}

    idx_set = {c.idx for c in candidates}
    title = re.sub(r"\s+", " ", (episode.get("title") or "").strip()) or f"식물 육종 뉴스 팟캐스트 ({range_end})"
    desc = re.sub(r"\s+", " ", (episode.get("shortDescription") or "").strip()) or "최신 식물 육종 뉴스를 대화형으로 정리한 에피소드입니다."

    selected: list[dict[str, Any]] = []
    for obj in episode.get("selectedItems") or []:
        if not isinstance(obj, dict):
            continue
        try:
            idx = int(obj.get("idx"))
        except Exception:
            continue
        if idx not in idx_set or any(x["idx"] == idx for x in selected):
            continue
        reason = re.sub(r"\s+", " ", (obj.get("reason") or "").strip()) or "중요 기사로 선택"
        selected.append({"idx": idx, "reason": reason})

    if len(selected) < 3:
        selected = [{"idx": c.idx, "reason": "키워드 점수와 최신성을 기준으로 선택"} for c in candidates[:6]]

    dialogue: list[dict[str, str]] = []
    for i, obj in enumerate(episode.get("dialogue") or []):
        if not isinstance(obj, dict):
            continue
        speaker = (obj.get("speaker") or "").strip()
        if speaker not in {"지윤", "민종"}:
            speaker = "지윤" if i % 2 == 0 else "민종"
        text = re.sub(r"\s+", " ", (obj.get("text") or "").strip())
        if text:
            dialogue.append({"speaker": speaker, "text": text})

    if len(dialogue) < 4:
        fallback = _fallback_episode(candidates, range_start=range_start, range_end=range_end)
        dialogue = fallback["dialogue"]

    return {
        "title": title,
        "shortDescription": desc,
        "selectedItems": selected[:8],
        "dialogue": dialogue[:16],
    }


def _synthesize_episode_audio(
    episode: dict[str, Any],
    *,
    podcast_dir: str,
    release_date: str,
    api_key: str,
    model: str,
    keep_wav: bool,
) -> dict[str, Any]:
    pcm = _call_gemini_tts(_tts_prompt(episode), api_key=api_key, model=model)

    wav_name = f"{release_date}.wav"
    wav_path = os.path.join(podcast_dir, wav_name)
    _write_wav(wav_path, pcm)

    duration_s = round(len(pcm) / (24000 * 2), 2)
    audio_path = wav_path
    audio_name = wav_name
    mime = "audio/wav"

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        mp3_name = f"{release_date}.mp3"
        mp3_path = os.path.join(podcast_dir, mp3_name)
        try:
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    wav_path,
                    "-codec:a",
                    "libmp3lame",
                    "-b:a",
                    "64k",
                    mp3_path,
                ],
                check=True,
            )
            if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
                audio_path = mp3_path
                audio_name = mp3_name
                mime = "audio/mpeg"
                if not keep_wav:
                    try:
                        os.remove(wav_path)
                    except OSError:
                        pass
        except (OSError, subprocess.SubprocessError):
            try:
                if os.path.exists(mp3_path) and os.path.getsize(mp3_path) == 0:
                    os.remove(mp3_path)
            except OSError:
                pass

    return {
        "url": audio_name,
        "mimeType": mime,
        "durationSeconds": duration_s,
        "bytes": os.path.getsize(audio_path),
    }


def _tts_prompt(episode: dict[str, Any]) -> str:
    lines = [
        "TTS the following Korean podcast conversation.",
        "Make 지윤 sound warm, bright, and conversational.",
        "Make 민종 sound knowledgeable, calm, and clear.",
        "Keep a polished weekly news podcast tone.",
        "",
    ]
    for line in episode.get("dialogue") or []:
        lines.append(f"{line['speaker']}: {line['text']}")
    return "\n".join(lines).strip() + "\n"


def _call_gemini_tts(prompt: str, *, api_key: str, model: str, timeout_s: int = 180, attempts: int = 3) -> bytes:
    import requests

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "multiSpeakerVoiceConfig": {
                    "speakerVoiceConfigs": [
                        {
                            "speaker": "지윤",
                            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}},
                        },
                        {
                            "speaker": "민종",
                            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Zephyr"}},
                        },
                    ]
                }
            },
        },
    }
    last_error = ""
    max_attempts = max(1, attempts)
    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
        except requests.RequestException as e:
            last_error = str(e)
            if attempt >= max_attempts:
                raise RuntimeError(f"Gemini TTS request failed: {last_error}")
            time.sleep(min(2 ** (attempt - 1), 5))
            continue

        if r.status_code >= 500 and attempt < max_attempts:
            last_error = f"Gemini TTS HTTP {r.status_code}: {r.text[:500]}"
            time.sleep(min(2 ** (attempt - 1), 5))
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"Gemini TTS HTTP {r.status_code}: {r.text[:500]}")

        data = r.json()
        try:
            encoded = data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        except Exception:
            raise RuntimeError(f"Gemini TTS response missing audio: {json.dumps(data, ensure_ascii=False)[:500]}")
        return base64.b64decode(encoded)

    raise RuntimeError(last_error or "Gemini TTS failed")


def _write_wav(path: str, pcm: bytes) -> None:
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(pcm)


def _episode_payload(
    episode: dict[str, Any],
    *,
    candidates: list[PodcastCandidate],
    release_date: str,
    range_start: str,
    range_end: str,
    script_model: str,
    tts_model: str,
    audio_meta: dict[str, Any],
) -> dict[str, Any]:
    by_idx = {c.idx: c for c in candidates}
    selected = []
    for obj in episode.get("selectedItems") or []:
        c = by_idx.get(int(obj["idx"]))
        if not c:
            continue
        selected.append(
            {
                "idx": c.idx,
                "date": c.date,
                "source": c.source,
                "title": c.title,
                "itemPath": c.item_path,
                "originalUrl": c.original_url,
                "reason": obj.get("reason") or "",
            }
        )

    return {
        "title": episode["title"],
        "shortDescription": episode["shortDescription"],
        "releasedDate": release_date,
        "rangeStart": range_start,
        "rangeEnd": range_end,
        "staticRelease": True,
        "models": {
            "script": script_model,
            "tts": tts_model,
        },
        "audio": audio_meta,
        "selectedItems": selected,
        "dialogue": episode["dialogue"],
    }


def _write_json(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _write_episode_md(path: str, payload: dict[str, Any]) -> None:
    audio = payload.get("audio") or {}
    lines: list[str] = []
    lines.append("---")
    lines.append(f"title: {json.dumps(payload.get('title') or '', ensure_ascii=False)}")
    lines.append(f"released_date: {json.dumps(payload.get('releasedDate') or '', ensure_ascii=False)}")
    lines.append("---\n")
    lines.append(f"# {payload.get('title')}\n")
    lines.append(f"{payload.get('shortDescription')}\n")
    if audio.get("url"):
        lines.append(f'<audio controls preload="metadata" src="{audio["url"]}"></audio>\n')
        if audio.get("durationSeconds"):
            lines.append(f"- 길이: 약 {_fmt_duration(float(audio['durationSeconds']))}")
        if audio.get("bytes"):
            lines.append(f"- 파일 크기: {round(int(audio['bytes']) / 1024 / 1024, 2)} MB")
        lines.append("")
    else:
        lines.append("> 아직 오디오 파일은 생성되지 않았습니다. 대본만 제공됩니다.\n")

    lines.append("## 다룬 기사\n")
    for it in payload.get("selectedItems") or []:
        item_path = it.get("itemPath") or ""
        local_link = f"../{item_path}" if item_path else ""
        title = it.get("title") or "기사"
        original = it.get("originalUrl") or ""
        suffix = f" · [원문]({original})" if original else ""
        if local_link:
            lines.append(f"- **[{title}]({local_link})** ({it.get('source')}, {it.get('date')}){suffix}")
        else:
            lines.append(f"- **{title}** ({it.get('source')}, {it.get('date')}){suffix}")
        reason = (it.get("reason") or "").strip()
        if reason:
            lines.append(f"  - {reason}")
    lines.append("")

    lines.append("## 대본\n")
    for line in payload.get("dialogue") or []:
        lines.append(f"**{line.get('speaker')}**: {line.get('text')}\n")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")


def _write_index(*, podcast_dir: str, site_url: str) -> str:
    episodes = _load_episode_payloads(podcast_dir)
    path = os.path.join(podcast_dir, "index.md")
    lines: list[str] = []
    lines.append("---")
    lines.append('title: "식물 육종 뉴스 팟캐스트"')
    lines.append("---\n")
    lines.append("# 식물 육종 뉴스 팟캐스트\n")
    lines.append("최신 식물 육종·종자·품종 뉴스를 AI가 선별해 한국어 대화형 오디오로 정리합니다.\n")
    lines.append("- [홈으로](../index.md)")
    lines.append("- [RSS 피드](feed.xml)\n")

    if not episodes:
        lines.append("(아직 생성된 에피소드가 없습니다.)\n")
    else:
        latest = episodes[0]
        lines.append("## 최신 에피소드\n")
        lines.append(_episode_card_md(latest))
        if len(episodes) > 1:
            lines.append("## 지난 에피소드\n")
            for ep in episodes[1:]:
                lines.append(_episode_card_md(ep))

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    return path


def _episode_card_md(payload: dict[str, Any]) -> str:
    date = payload.get("releasedDate") or ""
    page = f"{date}.md" if date else ""
    title = payload.get("title") or "에피소드"
    desc = payload.get("shortDescription") or ""
    audio = payload.get("audio") or {}
    lines = [f"### [{title}]({page})\n", desc, ""]
    if audio.get("url"):
        lines.append(f'<audio controls preload="metadata" src="{audio["url"]}"></audio>')
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write_feed(*, podcast_dir: str, site_url: str) -> str:
    episodes = [ep for ep in _load_episode_payloads(podcast_dir) if (ep.get("audio") or {}).get("url")]
    base_url = site_url.rstrip("/") + "/" + PODCAST_DIRNAME
    now = format_datetime(datetime.now().astimezone())

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        "<channel>",
        "<title>식물 육종 뉴스 팟캐스트</title>",
        f"<link>{escape(base_url + '/')}</link>",
        "<description>AI가 선별하고 낭독하는 식물 육종·종자·품종 주간 뉴스</description>",
        "<language>ko-kr</language>",
        f"<lastBuildDate>{escape(now)}</lastBuildDate>",
    ]

    for ep in episodes[:20]:
        audio = ep.get("audio") or {}
        date_s = ep.get("releasedDate") or ""
        item_url = f"{base_url}/{date_s}.html"
        audio_url = f"{base_url}/{audio.get('url')}"
        pub_dt = _parse_dt(f"{date_s}T00:00:00+09:00") or datetime.now().astimezone()
        lines.extend(
            [
                "<item>",
                f"<title>{escape(ep.get('title') or '에피소드')}</title>",
                f"<description>{escape(ep.get('shortDescription') or '')}</description>",
                f"<link>{escape(item_url)}</link>",
                f"<guid>{escape(item_url)}</guid>",
                f"<pubDate>{escape(format_datetime(pub_dt))}</pubDate>",
                f'<enclosure url="{escape(audio_url)}" length="{int(audio.get("bytes") or 0)}" type="{escape(audio.get("mimeType") or "audio/mpeg")}" />',
                "</item>",
            ]
        )

    lines.extend(["</channel>", "</rss>"])
    path = os.path.join(podcast_dir, "feed.xml")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def _load_episode_payloads(podcast_dir: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not os.path.exists(podcast_dir):
        return out
    for name in os.listdir(podcast_dir):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", name):
            continue
        path = os.path.join(podcast_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                out.append(json.load(f))
        except Exception:
            continue
    out.sort(key=lambda ep: ep.get("releasedDate") or "", reverse=True)
    return out


def _load_existing_audio_payload(*, podcast_dir: str, release_date: str) -> dict[str, Any]:
    for name in (f"{release_date}.json", "latest.json"):
        path = os.path.join(podcast_dir, name)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            continue
        if payload.get("releasedDate") != release_date:
            continue
        audio = payload.get("audio") or {}
        audio_name = audio.get("url") or ""
        if audio_name and os.path.exists(os.path.join(podcast_dir, audio_name)):
            return payload
    return {}


def _has_recent_episode(*, podcast_dir: str, now_kst: datetime, min_days_between: int) -> bool:
    latest_path = os.path.join(podcast_dir, "latest.json")
    if min_days_between <= 0 or not os.path.exists(latest_path):
        return False
    try:
        with open(latest_path, "r", encoding="utf-8") as f:
            latest = json.load(f)
    except Exception:
        return False

    released = _parse_dt(latest.get("releasedDate"))
    if released is None:
        return False
    released_kst = _to_tz(released, now_kst.tzinfo)
    return (now_kst.date() - released_kst.date()).days < min_days_between


def _fmt_duration(seconds: float) -> str:
    total = int(round(seconds))
    m, s = divmod(total, 60)
    return f"{m}분 {s:02d}초"
