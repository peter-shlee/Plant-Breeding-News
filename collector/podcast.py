from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import time
import wave
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from email.utils import format_datetime
from typing import Any, Iterable, Optional
from xml.sax.saxutils import escape

from dateutil import parser

from .sitegen import item_relpath


DEFAULT_SCRIPT_MODEL = "gemini-3.5-flash"
DEFAULT_TTS_MODEL = "gemini-3.1-flash-tts-preview"
DEFAULT_TTS_FALLBACK_MODELS = ("gemini-2.5-flash-preview-tts",)
DEFAULT_SITE_URL = "https://peter-shlee.github.io/Plant-Breeding-News"
PODCAST_DIRNAME = "podcast"
HOST_LEAD = "재석"
HOST_EXPERT = "민아"
HOST_LEAD_TTS_VOICE = "Puck"
HOST_EXPERT_TTS_VOICE = "Zephyr"
MAX_PROMPT_ARTICLE_CHARS = 24000
MAX_ARTICLE_BODY_CHARS = 6000
MIN_DETAIL_ARTICLE_CHARS = 1200


@dataclass(frozen=True)
class PodcastCandidate:
    idx: int
    date: str
    source: str
    title: str
    item_path: str
    original_url: str
    article_body: str
    tags: tuple[str, ...]
    score: float


def build_podcast(
    items: Iterable[dict[str, Any]],
    *,
    outdir: str,
    days: int = 7,
    max_candidates: int = 5,
    target_minutes: int = 8,
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
    api_key = os.getenv("GEMINI_API_KEY") or ""

    if not force and _has_recent_episode(
        podcast_dir=podcast_dir,
        now_kst=now_kst,
        min_days_between=min_days_between,
        api_key_present=bool(api_key),
        skip_audio=skip_audio,
    ):
        index_path = _write_index(podcast_dir=podcast_dir, site_url=site_url)
        feed_path = _write_feed(podcast_dir=podcast_dir, site_url=site_url)
        return {
            "status": "skipped_recent_episode",
            "podcast_dir": os.path.relpath(podcast_dir, outdir),
            "index": os.path.relpath(index_path, outdir),
            "feed": os.path.relpath(feed_path, outdir),
        }

    candidates = _select_candidates(items, days=days, max_candidates=max_candidates, now=now_kst)
    candidates = _hydrate_summary_candidates(candidates)
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
    if script_status == "ok" and _has_untranslated_dialogue(episode):
        episode = _fallback_episode(candidates, range_start=range_start, range_end=range_end)
        script_status = "fallback_untranslated_dialogue"

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

    payload = _episode_payload(
        episode,
        candidates=candidates,
        release_date=release_date,
        range_start=range_start,
        range_end=range_end,
        script_model=script_model,
        tts_model=tts_model,
        audio_meta=audio_meta,
        script_status=script_status,
        audio_status=audio_status,
    )

    preserved_existing_audio = False
    if not audio_meta and audio_status.startswith("tts_error:"):
        existing_payload = _load_existing_audio_payload(podcast_dir=podcast_dir, release_date=release_date)
        if existing_payload:
            payload = existing_payload
            preserved_existing_audio = True
            audio_status = f"{audio_status}_preserved_existing_episode"
        else:
            payload["generation"]["audioStatus"] = audio_status

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


def _article_body(it: dict[str, Any]) -> str:
    text = (it.get("content_text") or "").strip()
    if not text:
        text = (it.get("summary") or "").strip()
    text = re.sub(r"\s+", " ", text).strip()
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
        # Prefer richer article bodies when duplicate feed/detail entries exist.
        if len(_article_body(it)) > len(_article_body(prev)):
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
                article_body=_article_body(it),
                tags=tuple(it.get("tags") or []),
                score=round(score, 2),
            )
        )
    return candidates


def _hydrate_summary_candidates(candidates: list[PodcastCandidate]) -> list[PodcastCandidate]:
    """Fetch fuller article bodies only for selected summary-backed RSS candidates."""
    if not candidates:
        return candidates
    try:
        from .http import HttpClient
        from .sources import SOURCES
    except Exception:
        return candidates

    http = HttpClient()
    hydrated: list[PodcastCandidate] = []
    for c in candidates:
        source_cls = SOURCES.get(c.source)
        if not source_cls or not bool(getattr(source_cls, "list_content_is_summary", False)):
            hydrated.append(c)
            continue
        if len(c.article_body) >= MIN_DETAIL_ARTICLE_CHARS:
            hydrated.append(c)
            continue
        try:
            detail_text, _attachments, _tags, _raw_html = source_cls(http).fetch_detail(str(c.idx), c.original_url)
        except Exception:
            hydrated.append(c)
            continue
        detail_body = _normalize_article_body(detail_text)
        if _is_better_article_body(detail_body, c.article_body):
            hydrated.append(replace(c, article_body=detail_body))
        else:
            hydrated.append(c)
    return hydrated


def _normalize_article_body(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _is_better_article_body(candidate: str, fallback: str) -> bool:
    if len(candidate) < MIN_DETAIL_ARTICLE_CHARS:
        return False
    if len(candidate) < max(len(fallback) * 2, MIN_DETAIL_ARTICLE_CHARS):
        return False
    lowered = candidate[:240].lower()
    noisy_starts = ("skip to content", "subscribe", "sign in", "advertisement")
    return not any(marker in lowered for marker in noisy_starts)


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
                        "speaker": {
                            "type": "string",
                            "description": f"반드시 {HOST_LEAD} 또는 {HOST_EXPERT} 중 하나",
                        },
                        "text": {
                            "type": "string",
                            "description": "자연스러운 한국어 대사. 영어 문장이나 영어 기사 제목을 그대로 넣지 않는다.",
                        },
                    },
                    "required": ["speaker", "text"],
                },
            },
        },
        "required": ["title", "shortDescription", "selectedItems", "dialogue"],
    }

    prompt = _script_prompt(candidates, range_start=range_start, range_end=range_end, target_minutes=target_minutes)
    text = _call_gemini_jsonish(prompt, api_key=api_key, model=model, schema=schema, max_tokens=8192)
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
    lines.append("후보의 title과 article_body가 영어 등 외국어여도, 청취자에게 들려주는 모든 설명은 자연스러운 한국어 번역·의역으로 바꿔 말한다.")
    lines.append("")
    lines.append("[진행자]")
    lines.append(f"- {HOST_LEAD}: 친근하고 매끄러운 메인 진행자. 청취자 눈높이에서 흐름을 잡고, 어려운 외국어 기사 제목과 내용을 한국어로 자연스럽게 풀어 소개한다.")
    lines.append(f"- {HOST_EXPERT}: 식물 육종 전문가. QTL, 분자표지, CRISPR, 유전체선발, 품종보호 같은 기술 맥락을 쉽고 정확한 한국어로 설명한다.")
    lines.append("")
    lines.append("[규칙]")
    lines.append(f"- 기간: {range_start} ~ {range_end}")
    lines.append("- selectedItems는 아래 후보의 idx 중 가장 중요한 기사만 고르되, 최대 5개를 넘기지 않는다.")
    lines.append("- 제공되지 않은 기사, 통계, 링크, 인물 발언은 만들지 않는다.")
    lines.append("- title과 article_body를 그대로 낭독하지 말고, 핵심 의미를 한국어로 번역·요약해서 말한다.")
    lines.append("- 각 기사에서 배경, 핵심 주장, 연구·산업적 의미, 현장 영향까지 뽑아 대화에 반영한다.")
    lines.append("- 영어 문장, 영어 기사 제목, 영어 본문 조각을 대사에 그대로 넣지 않는다.")
    lines.append("- 기관명, 품종명, 유전자명, 약어(QTL, GWAS, CRISPR, SNP 등)는 원문 표기를 유지해도 된다.")
    lines.append("- 전문용어는 정확하게 쓰되, 개인 청취자가 이해할 수 있게 한 문장 안에서 풀어준다.")
    lines.append(f"- 대본은 약 {target_minutes}분 분량으로, 14~18턴의 자연스러운 대화로 작성한다.")
    lines.append("- 선택한 각 기사마다 최소 2턴 이상 다루고, 단순 소개가 아니라 왜 중요한지와 현장/산업적 함의를 설명한다.")
    lines.append("- 각 대사는 2~4문장으로 쓴다. 너무 짧은 한 문장 답변으로 끝내지 않는다.")
    lines.append("- 전체 대사 분량은 충분히 길게 작성하되, 반복 멘트나 빈 인사는 늘리지 않는다. selectedItems.reason은 80자 이내 한국어로 쓴다.")
    lines.append(f"- speaker 값은 반드시 '{HOST_LEAD}' 또는 '{HOST_EXPERT}'만 사용한다.")
    lines.append("- JSON 객체만 출력한다. 코드블록 금지. 문자열은 끝까지 닫아서 유효한 JSON으로 출력한다.")
    lines.append("")
    lines.append("[기사 후보]")
    body_budget = _article_body_prompt_budget(len(candidates))
    for c in candidates:
        tags = ", ".join(c.tags) if c.tags else "-"
        lines.append(f"idx={c.idx} | date={c.date} | source={c.source} | score={c.score:g}")
        lines.append(f"title: {c.title}")
        lines.append(f"url: {c.original_url}")
        lines.append(f"tags: {tags}")
        lines.append(f"article_body: {_trim_article_body_for_prompt(c.article_body, body_budget) or '(본문 없음)'}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _article_body_prompt_budget(candidate_count: int) -> int:
    count = max(1, candidate_count)
    return min(MAX_ARTICLE_BODY_CHARS, max(MIN_DETAIL_ARTICLE_CHARS, MAX_PROMPT_ARTICLE_CHARS // count))


def _trim_article_body_for_prompt(text: str, max_chars: int) -> str:
    body = _normalize_article_body(text)
    if len(body) <= max_chars:
        return body
    cutoff = max_chars - 1
    boundary = max(body.rfind(". ", 0, cutoff), body.rfind("? ", 0, cutoff), body.rfind("! ", 0, cutoff), body.rfind("。", 0, cutoff), body.rfind("다. ", 0, cutoff))
    if boundary < max_chars * 0.65:
        boundary = cutoff
    return body[:boundary].rstrip() + "…"


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
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
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
    selected = candidates[:5]
    title = f"식물 육종 뉴스 팟캐스트 ({range_end})"
    short = "이번 주 식물 육종·종자·품종 관련 핵심 소식을 요약했다."

    dialogue: list[dict[str, str]] = [
        {
            "speaker": HOST_LEAD,
            "text": f"안녕하세요. 식물 육종 뉴스입니다. 오늘은 {range_start}부터 {range_end}까지 들어온 소식 중 눈에 띄는 흐름을 짚어보겠습니다.",
        },
        {
            "speaker": HOST_EXPERT,
            "text": "이번 주는 품종 개발, 종자 산업, 유전체 기술, 현장 적용 이슈를 한국어로 풀어 정리해 보겠습니다.",
        },
    ]
    for c in selected:
        topic = _fallback_topic(c)
        headline = _korean_safe_headline(c)
        dialogue.append(
            {
                "speaker": HOST_LEAD,
                "text": f"다음은 {c.source}에서 다룬 {headline} 소식입니다.",
            }
        )
        dialogue.append(
            {
                "speaker": HOST_EXPERT,
                "text": f"핵심은 {topic}입니다. 원문 표현을 그대로 읽기보다는, 육종 현장에서 어떤 기술이나 제도 변화로 이어질지 살펴볼 만한 기사입니다.",
            }
        )
    dialogue.append(
        {
            "speaker": HOST_LEAD,
            "text": "오늘 준비한 소식은 여기까지입니다. 원문 링크와 대본은 팟캐스트 페이지에서 확인하실 수 있습니다.",
        }
    )

    return {
        "title": title,
        "shortDescription": short,
        "selectedItems": [{"idx": c.idx, "reason": "키워드 점수와 최신성을 기준으로 선택"} for c in selected],
        "dialogue": dialogue,
    }


def _korean_safe_headline(c: PodcastCandidate) -> str:
    title = re.sub(r"\s+", " ", c.title or "").strip()
    if title and _hangul_ratio(title) >= 0.35:
        return title
    return _fallback_topic(c)


def _hangul_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    hangul = [ch for ch in letters if "가" <= ch <= "힣"]
    return len(hangul) / len(letters)


def _fallback_topic(c: PodcastCandidate) -> str:
    text = " ".join([c.title, c.article_body, " ".join(c.tags)]).lower()
    topics = [
        (("ai", "artificial intelligence", "prediction", "predictive", "genomic selection"), "AI와 유전체 예측을 활용한 신육종 기술"),
        (("crispr", "gene editing", "genome editing", "유전자편집"), "CRISPR와 유전자편집 기반 품종 개발"),
        (("qtl", "gwas", "snp", "marker", "마커"), "분자표지와 유전체 분석을 활용한 선발 전략"),
        (("climate", "heat", "drought", "stress", "고온", "가뭄"), "기후 스트레스에 대응하는 내재해성 품종 개발"),
        (("seed", "variety", "cultivar", "종자", "품종"), "종자 산업과 신품종 개발 동향"),
        (("wheat", "rice", "soybean", "corn", "maize", "밀", "벼", "콩", "옥수수"), "주요 작물의 유전자원과 품종 개선"),
        (("policy", "regulation", "plant variety protection", "upov", "품종보호"), "품종보호와 육종 관련 제도 변화"),
    ]
    for keywords, topic in topics:
        if any(kw in text for kw in keywords):
            return topic
    return "식물 육종과 종자 기술의 최신 흐름"


_ALLOWED_UPPER_TERMS = {
    "AI",
    "CRISPR",
    "DNA",
    "GWAS",
    "KASP",
    "QTL",
    "RNA",
    "SNP",
    "UPOV",
}


def _has_untranslated_dialogue(episode: dict[str, Any]) -> bool:
    for line in episode.get("dialogue") or []:
        if not isinstance(line, dict):
            continue
        text = str(line.get("text") or "")
        if _looks_like_untranslated_text(text):
            return True
    return False


def _looks_like_untranslated_text(text: str) -> bool:
    letters = re.findall(r"[A-Za-z가-힣]", text)
    if not letters:
        return False
    latin_words = re.findall(r"\b[A-Za-z][A-Za-z'\-]{2,}\b", text)
    disallowed = [w for w in latin_words if w.upper() not in _ALLOWED_UPPER_TERMS]
    if len(disallowed) >= 5:
        return True
    latin_letters = sum(1 for ch in letters if ("A" <= ch <= "Z") or ("a" <= ch <= "z"))
    hangul_letters = sum(1 for ch in letters if "가" <= ch <= "힣")
    return latin_letters >= 30 and latin_letters > hangul_letters


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
        selected = [{"idx": c.idx, "reason": "키워드 점수와 최신성을 기준으로 선택"} for c in candidates[:5]]

    dialogue: list[dict[str, str]] = []
    for i, obj in enumerate(episode.get("dialogue") or []):
        if not isinstance(obj, dict):
            continue
        speaker = (obj.get("speaker") or "").strip()
        if speaker not in {HOST_LEAD, HOST_EXPERT}:
            speaker = HOST_LEAD if i % 2 == 0 else HOST_EXPERT
        text = re.sub(r"\s+", " ", (obj.get("text") or "").strip())
        if text:
            dialogue.append({"speaker": speaker, "text": text})

    if len(dialogue) < 4:
        fallback = _fallback_episode(candidates, range_start=range_start, range_end=range_end)
        dialogue = fallback["dialogue"]

    return {
        "title": title,
        "shortDescription": desc,
        "selectedItems": selected[:5],
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
    errors: list[str] = []
    pcm = b""
    synthesis_mode = ""
    fallback_reason = ""
    used_model = model

    for candidate_model in _tts_model_candidates(model):
        try:
            pcm, synthesis_mode, fallback_reason = _synthesize_episode_pcm(
                episode,
                api_key=api_key,
                model=candidate_model,
            )
            used_model = candidate_model
            break
        except Exception as e:
            errors.append(f"{candidate_model}: {e}")

    if not pcm:
        raise RuntimeError("; ".join(errors) or "TTS produced no audio")

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

    meta = {
        "url": audio_name,
        "mimeType": mime,
        "durationSeconds": duration_s,
        "bytes": os.path.getsize(audio_path),
        "synthesisMode": synthesis_mode,
        "ttsModel": used_model,
    }
    if used_model != model:
        meta["primaryTtsModel"] = model
        if errors:
            meta["modelFallbackReason"] = "; ".join(errors)[:500]
    if fallback_reason:
        meta["fallbackReason"] = fallback_reason[:300]
    return meta


def _tts_model_candidates(primary_model: str) -> list[str]:
    candidates = [primary_model]
    for fallback in DEFAULT_TTS_FALLBACK_MODELS:
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates


def _synthesize_episode_pcm(episode: dict[str, Any], *, api_key: str, model: str) -> tuple[bytes, str, str]:
    try:
        return _call_gemini_tts(_tts_prompt(episode), api_key=api_key, model=model), "multi_speaker", ""
    except Exception as e:
        multi_speaker_error = str(e)

    try:
        return (
            _synthesize_episode_audio_by_line(episode, api_key=api_key, model=model),
            "single_speaker_fallback",
            multi_speaker_error,
        )
    except Exception as e:
        raise RuntimeError(
            f"multi-speaker TTS failed: {multi_speaker_error}; single-line TTS fallback failed: {e}"
        ) from e


def _synthesize_episode_audio_by_line(episode: dict[str, Any], *, api_key: str, model: str) -> bytes:
    chunks: list[bytes] = []
    pause = _pcm_silence(0.35)
    voice_by_speaker = {
        HOST_LEAD: HOST_LEAD_TTS_VOICE,
        HOST_EXPERT: HOST_EXPERT_TTS_VOICE,
    }

    for idx, line in enumerate(episode.get("dialogue") or [], start=1):
        if not isinstance(line, dict):
            continue
        text = re.sub(r"\s+", " ", str(line.get("text") or "").strip())
        if not text:
            continue
        speaker = str(line.get("speaker") or "")
        voice_name = voice_by_speaker.get(speaker, HOST_EXPERT_TTS_VOICE)
        try:
            pcm = _call_gemini_tts_voice(text, api_key=api_key, model=model, voice_name=voice_name)
        except Exception as e:
            raise RuntimeError(f"single-line TTS failed at turn {idx}: {e}") from e
        if chunks:
            chunks.append(pause)
        chunks.append(pcm)

    if not chunks:
        raise RuntimeError("single-line TTS fallback produced no audio")
    return b"".join(chunks)


def _pcm_silence(seconds: float) -> bytes:
    frame_count = max(0, int(round(seconds * 24000)))
    return b"\x00\x00" * frame_count


def _tts_prompt(episode: dict[str, Any]) -> str:
    lines = [
        "TTS the following Korean podcast conversation.",
        "The dialogue must be read as Korean. Do not switch into English narration except for short technical abbreviations.",
        "Use the configured prebuilt voices only; do not imitate any real person's voice or mannerisms.",
        f"Make the {HOST_LEAD} speaker sound like an upbeat, lower-pitched male Korean podcast host.",
        f"Make the {HOST_EXPERT} speaker sound knowledgeable, friendly, and concise.",
        "Keep a polished weekly news podcast tone.",
        "",
    ]
    for line in episode.get("dialogue") or []:
        lines.append(f"{line['speaker']}: {line['text']}")
    return "\n".join(lines).strip() + "\n"


def _call_gemini_tts(prompt: str, *, api_key: str, model: str, timeout_s: int = 180, attempts: int = 1) -> bytes:
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "multiSpeakerVoiceConfig": {
                    "speakerVoiceConfigs": [
                        {
                            "speaker": HOST_LEAD,
                            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": HOST_LEAD_TTS_VOICE}},
                        },
                        {
                            "speaker": HOST_EXPERT,
                            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": HOST_EXPERT_TTS_VOICE}},
                        },
                    ]
                }
            },
        },
    }
    return _post_gemini_tts_payload(payload, api_key=api_key, model=model, timeout_s=timeout_s, attempts=attempts)


def _call_gemini_tts_voice(
    text: str,
    *,
    api_key: str,
    model: str,
    voice_name: str,
    timeout_s: int = 60,
    attempts: int = 2,
) -> bytes:
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": voice_name},
                }
            },
        },
    }
    return _post_gemini_tts_payload(payload, api_key=api_key, model=model, timeout_s=timeout_s, attempts=attempts)


def _post_gemini_tts_payload(
    payload: dict[str, Any],
    *,
    api_key: str,
    model: str,
    timeout_s: int,
    attempts: int,
) -> bytes:
    import requests

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
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
    script_status: str,
    audio_status: str,
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
        "generation": {
            "scriptStatus": script_status,
            "audioStatus": audio_status,
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
    playable_episodes = [ep for ep in episodes if _episode_audio_exists(podcast_dir, ep)]
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
        latest = playable_episodes[0] if playable_episodes else episodes[0]
        lines.append("## 최신 에피소드\n")
        lines.append(_episode_card_md(latest))
        previous = [ep for ep in episodes if ep.get("releasedDate") != latest.get("releasedDate")]
        if previous:
            lines.append("## 지난 에피소드\n")
            for ep in previous:
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
    episodes = [ep for ep in _load_episode_payloads(podcast_dir) if _episode_audio_exists(podcast_dir, ep)]
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


def _episode_audio_exists(podcast_dir: str, payload: dict[str, Any]) -> bool:
    audio = payload.get("audio") or {}
    audio_name = audio.get("url") or ""
    return bool(audio_name and os.path.exists(os.path.join(podcast_dir, audio_name)))


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
        if _episode_audio_exists(podcast_dir, payload):
            return payload
    return {}


def _has_recent_episode(
    *,
    podcast_dir: str,
    now_kst: datetime,
    min_days_between: int,
    api_key_present: bool,
    skip_audio: bool,
) -> bool:
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
    if (now_kst.date() - released_kst.date()).days >= min_days_between:
        return False
    has_audio = _episode_audio_exists(podcast_dir, latest)
    if has_audio:
        return True
    if api_key_present and not skip_audio:
        return False
    return True


def _fmt_duration(seconds: float) -> str:
    total = int(round(seconds))
    m, s = divmod(total, 60)
    return f"{m}분 {s:02d}초"
