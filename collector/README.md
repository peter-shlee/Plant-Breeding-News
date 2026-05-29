# collector (MVP)

Weekly incremental press-release/news collector (Python 3) for:
- **RDA** (농촌진흥청) press list
- **NICS** (국립식량과학원) press list
- **NIHHS** (국립원예특작과학원) press list (requires a real User-Agent)
- **Seed World** RSS (`seedworld`)
- **ScienceDaily – Agriculture & Food** RSS (`sciencedaily`, keyword relevance filter enabled by default)

## Features

- Incremental collection (dedupe by `source + site_id` via SQLite unique constraint)
- Standardized item schema:
  - `id` (sha256 of `source:site_id`)
  - `source`, `org`, `site_id`, `title`, `published_at` (ISO8601 KST), `url`
  - `content_text`, `tags`, `attachments`, `fetched_at`, optional `raw_html`
- Storage:
  - **Default**: local SQLite (`.collector/collector.sqlite`) + JSONL export
  - **Optional**: Firestore writer (requires env vars + service account)
- Polite crawling: randomized delay + retries

## Setup

```bash
cd ~/dev/breeding-news-collector
python3 -m pip install -r requirements.txt
```

## GitHub Pages setup (no generator)

GitHub Pages는 기본 설정에서 **루트(/)** 또는 **/docs**만 소스로 선택할 수 있습니다. 그래서 이 프로젝트는 생성된 컨텐츠를 `docs/`에 두고 GitHub Pages에서 `/docs`를 publish 하는 방식을 권장합니다. (Jekyll이 기본으로 돌아가며 Markdown을 그대로 렌더링합니다.)

Recommended approach:

- `docs/`는 git에 **추적** (public content)
- 수집 상태/캐시 DB는 로컬로만 유지 권장: `.collector/collector.sqlite`

Minimal `docs/_config.yml`:

```yml
# docs/_config.yml
title: Breeding news digest
markdown: kramdown
```

Jekyll 처리를 끄고(raw 파일 서빙) 싶으면, 빈 파일을 추가:

- `docs/.nojekyll`

(If you disable Jekyll, your Markdown will not be rendered to HTML by GitHub Pages. Most people should **not** use `.nojekyll` here.)

## Run collector

Collect recent items (default 30 days):

```bash
python3 -m collector run --sources rda nics nihhs seedworld sciencedaily --since-days 30 --verbose
```

Save raw HTML into SQLite (bigger DB):

```bash
python3 -m collector run --sources rda nihhs --since-days 30 --save-raw-html
```

## Export JSONL

```bash
python3 -m collector export-jsonl --out .collector/export.jsonl
```

## Export Markdown for GitHub Pages (to docs/)

Generate per-item Markdown files (SSOT as text files), without downloading attachments (only links are kept):

```bash
python3 -m collector export-md --outdir docs --days 7
```

This creates/updates files like:

- `docs/items/<source>/YYYY/MM/<site_id>.md`

Each file includes YAML frontmatter (id/source/org/site_id/published_at/url/attachments/tags/fetched_at) and a body with the title, content text, and an **Original** link.

## Build weekly digest pages

Build a digest for the last N days and update the index:

```bash
python3 -m collector build-weekly --outdir docs --days 7
```

Outputs:

- `docs/weekly/latest.md`
- `docs/weekly/YYYY-MM-DD.md` (run date in KST)
- `docs/index.md` (links to latest + archive)

## Build static AI podcast

Generate a Korean two-host podcast script and static podcast artifacts. Podcast prompts use article bodies from `content_text`, and foreign-language article titles and bodies are translated or paraphrased into Korean in the spoken dialogue:

```bash
GEMINI_API_KEY=... python3 -m collector build-podcast --outdir docs --days 7
```

Outputs:

- `docs/podcast/latest.json`
- `docs/podcast/YYYY-MM-DD.json`
- `docs/podcast/YYYY-MM-DD.md`
- `docs/podcast/YYYY-MM-DD.mp3` when TTS and `ffmpeg` succeed (falls back to WAV if `ffmpeg` is unavailable or conversion fails)
- `docs/podcast/index.md`
- `docs/podcast/feed.xml`

The command uses `gemini-3.5-flash` for script generation and `gemini-3.1-flash-tts-preview` for audio by default, with a TTS model fallback when the primary preview TTS model is unavailable. It targets an 8-minute episode unless `--target-minutes` is overridden. It is safe for CI: if `GEMINI_API_KEY` is missing, Gemini script generation fails, the generated script fails quality checks, or audio generation fails, it does not publish a fallback episode. Existing publishable episodes remain listed, and invalid same-day fallback artifacts are removed.

By default, the script passes only the top 5 scored article candidates to Gemini so each episode stays focused. For RSS sources, collection fetches the article detail page for new items where available, and podcast generation hydrates selected candidates again when only a short summary is available. Article bodies are capped before being sent to Gemini to keep prompt size predictable.

## Firestore (optional)

If you have Firebase service account credentials:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/serviceAccount.json"
export FIREBASE_PROJECT_ID="your-project-id"

python3 -m collector run --sources rda nics nihhs --since-days 30
```

Items are upserted into the `press_items` collection by default (override via `--firestore-collection`).

## Cron example

Run every Monday at 09:10 KST:

```cron
10 9 * * 1 cd /Users/peter/dev/breeding-news-collector && /usr/bin/python3 -m collector run --sources rda nics nihhs --since-days 30 >> .collector/cron.log 2>&1
```

## .gitignore recommendations

생성된 `docs/` 컨텐츠는 git에 **추적**하고, 로컬 런타임 파일은 ignore:

```gitignore
# local DB / runtime
.collector/collector.sqlite
.collector/collector.sqlite-*
.collector/cron.log

# optional exports (if you don't want to commit them)
.collector/export.jsonl
```

## Notes / Known limitations (MVP)

- **RSS sources (Seed World / ScienceDaily)**: list entries keep RSS `description` as a fallback. New items fetch detail pages where available; repo-known items skip collection-time detail fetch, but selected podcast candidates can still be hydrated at podcast generation time.
- **ScienceDaily relevance filter**: a light breeding/seed keyword score filter is applied to reduce noise.
- **NIHHS pagination**: list pagination is not fully implemented; MVP only scrapes the first page.
- **NICS detail page**: the site appears to require additional internal parameters for a view endpoint; MVP stores list metadata and attachment download links but may not retrieve full HTML article content.
- Page structures can change; selectors may need updating.
