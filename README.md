# breeding-news-collector

Incremental press-release/news collector (MVP) + GitHub Pages Markdown generator.

## Quickstart (local)

```bash
# (1) Fetch new items into SQLite
python3 -m collector run --since-days 30 --db .collector/collector.sqlite

# (2) Build weekly digest pages (docs/weekly/YYYY-MM-DD.md + latest.md)
python3 -m collector build-weekly --outdir docs --days 7 --db .collector/collector.sqlite

# (3) Build portal + per-source archive pages + item pages
python3 -m collector build-site --outdir docs --days 7 --limit 30 --db .collector/collector.sqlite
```

## Output structure (docs/)

- `docs/index.md` – portal page (recent items, weekly archive, source archive links)
- `docs/weekly/YYYY-MM-DD.md` – weekly digest page for the run date
- `docs/weekly/latest.md` – latest weekly digest (optional convenience)
- `docs/items/<source>/YYYY/MM/<site_id>.md` – per-item pages
- `docs/sources/<source>/index.md` – per-source archive pages (grouped by month)

## Default filtering (plant-only)

This repo is intended for **plant breeding / seed / cultivar / crop policy**.

- By default, the collector and all doc generators **exclude obvious animal/livestock/pet-related posts**.
- The filter is conservative: it does **not** require plant keywords, but if an animal keyword appears *and* plant/seed signals are present, the item is kept (to avoid dropping crop policy posts like "사료용 옥수수").
- If you need to adjust edge cases (e.g., include/exclude apiculture/sericulture), edit `collector/filtering.py`.

## GitHub Actions (CI)

A scheduled workflow updates `docs/` automatically:

- Workflow: `.github/workflows/update.yml`
- Schedule: **Mon/Wed/Fri 06:30 KST** (runs at Sun/Tue/Thu 21:30 UTC)
- Manual run: *Actions → Update docs → Run workflow*

CI is stateless, so the collector also performs a **repo-state dedupe**:

- It scans existing `docs/items/**/<site_id>.md` and treats them as already exported (`source:site_id`).
- If an item page already exists, it will skip the detail fetch to reduce load.

## Notes

- `build-site` loads items once (prefers SQLite; can fall back to JSONL via `--jsonl`) and reuses that data for:
  - exporting per-item Markdown pages (all items)
  - generating `docs/index.md`
  - generating `docs/sources/<source>/index.md`
- All links are relative and should work on GitHub Pages.
