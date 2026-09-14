# Jianke Yu — Academic Homepage

Personal academic website of **Jianke Yu (俞鉴珂)** — PhD (University of Technology Sydney),
graph machine learning & databases. Built with
[HugoBlox Academic CV](https://github.com/HugoBlox/theme-academic-cv) (MIT licensed template).

## What's inside

| Path | Purpose |
|---|---|
| `data/authors/me.yaml` | **Single source of truth** for the profile: bio, links, education, experience, awards, skills, languages |
| `content/_index.md` | Landing page blocks (biography → research → featured papers → full publication list) |
| `content/experience.md` | CV page blocks (education/experience, skills, awards, languages) |
| `content/publications/` | Publication pages — **generated** by the sync pipeline (do not edit by hand) |
| `scripts/sync_publications.py` | Syncs publications from OpenAlex (by ORCID), formats authors (own name bolded via `me`), adds CCF / 中科院分区 / JCR badges |
| `scripts/venues.yml` | Venue → classification map (CCF 2026 / CAS 2025 / JCR 2025). Add new venues here |
| `.github/workflows/sync-publications.yml` | Weekly cron that re-runs the sync and commits changes |
| `.github/workflows/build.yml` | Builds the site and deploys to GitHub Pages |

## Local development

```bash
# requires Hugo extended >= 0.162.0 and Go (for Hugo Modules)
hugo mod get          # fetch theme modules
hugo server           # http://localhost:1313
hugo --minify         # production build (optionally: pnpm install && pnpm run build)
```

## Publication pipeline

```bash
python3 scripts/sync_publications.py --dry-run   # preview
python3 scripts/sync_publications.py             # write content/publications/**
```

- Source: **OpenAlex** works for ORCID `0000-0002-2032-7727` (free API, no scraping).
- Filters out namesake papers (co-author whitelist), corrections, and arXiv duplicates.
- `authors:` uses the theme's `me` placeholder for the site owner → highlighted in listings.
- Badges come from `scripts/venues.yml`; unknown venues are logged so they can be added.

## Deployment

Pushing to `main` triggers the GitHub Actions build and publishes to GitHub Pages.
Custom domain / DNS is configured in the repository's Pages settings.

---

Template: [HugoBlox Academic CV](https://github.com/HugoBlox/theme-academic-cv) · MIT License.
