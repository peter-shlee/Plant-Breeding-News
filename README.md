# breeding-news-collector

Incremental press-release/news collector (MVP) + GitHub Pages Markdown generator.

## Quickstart

```bash
# (1) Fetch new items into SQLite
python3 -m collector run --db .collector/collector.sqlite

# (2) Build weekly digest pages (docs/weekly/YYYY-MM-DD.md + latest.md)
python3 -m collector build-weekly --outdir docs --days 7

# (3) Build portal + per-source archive pages + item pages
python3 -m collector build-site --outdir docs --days 7 --limit 25
```

## Output structure (docs/)

- `docs/index.md` – portal page (recent items, weekly archive, source archive links)
- `docs/weekly/YYYY-MM-DD.md` – weekly digest page for the run date
- `docs/weekly/latest.md` – latest weekly digest (optional convenience)
- `docs/items/<source>/YYYY/MM/<site_id>.md` – per-item pages
- `docs/sources/<source>/index.md` – per-source archive pages (grouped by month)

## Notes

- `build-site` loads items once (prefers SQLite; can fall back to JSONL via `--jsonl`) and reuses that data for:
  - exporting per-item Markdown pages (all items)
  - generating `docs/index.md`
  - generating `docs/sources/<source>/index.md`
- All links are relative and should work on GitHub Pages.
