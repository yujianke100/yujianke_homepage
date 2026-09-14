#!/usr/bin/env python3
"""Sync publications from OpenAlex (by ORCID) into HugoBlox Academic CV content.

- Source of truth: OpenAlex works filtered by ORCID (no scraping, free API).
- Filters: co-author whitelist (avoid namesake papers), dedupe by DOI, drop
  corrections/errata, drop arXiv-only duplicates when a published version exists.
- Enrichment: venue name (OpenAlex source -> Crossref fallback), author order
  (own name rendered as `me` so the theme bolds it), DOI/arXiv ids, citations,
  abstract, and classification badges (CCF / 中科院分区 / JCR) from venues.yml.
- Output: one HugoBlox publication page per paper:
      content/publications/<type>/<slug>/index.md

GENERATED FILES ARE OVERWRITTEN ON EACH RUN — do not edit them by hand.
Hand-written publications should live in their own folder (they won't be touched).

Usage:
    python3 scripts/sync_publications.py            # write files
    python3 scripts/sync_publications.py --dry-run  # print what would change
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import unicodedata
import urllib.parse
import urllib.request

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("pyyaml is required: pip install pyyaml")

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "content" / "publications"
VENUES_FILE = ROOT / "scripts" / "venues.yml"

ORCID = "0000-0002-2032-7727"
OWN_NAME = "Jianke Yu"
OWN_ALIASES = {"jianke yu", "yu jianke", "y. jianke"}
# Papers whose author list contains at least one of these people are trusted as
# genuinely his (guards against ORCID/OpenAlex author mis-assignment).
COAUTHOR_WHITELIST = {
    "Xiaoyang Wang", "Hanchen Wang", "Ying Zhang", "Lu Qin", "Wenjie Zhang",
    "Bailin Yang", "Zhao Li", "Jian Liao", "Xuemin Lin", "Longbin Lai",
    "Chen Chen", "Qing Sima", "Min Pei", "Xianhang Zhang", "Yongrui Gu",
    "Yunkai Lou", "Shunyang Li", "Xulu Gong", "Wenyuan Yu", "Kecheng Wang",
    "Xubo Wang", "Yuanhang Yu", "Dong Wen",
}
EXCLUDE_TITLE_RE = re.compile(r"^\s*(correction to|erratum|retraction)", re.I)
EXCLUDE_VENUE_RE = re.compile(r"^\s*(arxiv|coRR)", re.I)
FEATURED_VENUES = {"IEEE Transactions on Knowledge and Data Engineering", "ACM SIGKDD Conference on Knowledge Discovery and Data Mining", "ACM SIGMOD Conference"}
OPENALEX = "https://api.openalex.org/works"


def load_venues() -> dict:
    data = yaml.safe_load(VENUES_FILE.read_text(encoding="utf-8"))
    return {k: v for k, v in data.get("venues", {}).items() if isinstance(v, dict)}


def http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "jianke-homepage-sync/1.0 (mailto:yujianke100@gmail.com)"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_works() -> list[dict]:
    works, cursor = [], "*"
    fields = "id,doi,title,display_name,publication_year,publication_date,type,authorships,primary_location,locations,cited_by_count,abstract_inverted_index,ids,open_access,biblio"
    while cursor:
        q = urllib.parse.urlencode({
            "filter": f"author.orcid:{ORCID}",
            "per-page": "200",
            "cursor": cursor,
            "select": fields,
        })
        data = http_json(f"{OPENALEX}?{q}")
        works.extend(data.get("results", []))
        cursor = (data.get("meta") or {}).get("next_cursor")
        if not data.get("results"):
            break
    return works


def reconstruct_abstract(inverted: dict | None) -> str:
    if not inverted:
        return ""
    positions = [(p, w) for w, ps in inverted.items() for p in ps]
    positions.sort()
    return " ".join(w for _, w in positions)


def venue_of(work: dict) -> tuple[str, str]:
    """Return (venue_name, venue_type)."""
    src = ((work.get("primary_location") or {}).get("source") or {})
    name = src.get("display_name") or ""
    vtype = src.get("type") or ""
    if not name:
        for loc in work.get("locations") or []:
            s = (loc.get("source") or {})
            if s.get("display_name"):
                name, vtype = s["display_name"], s.get("type", "")
                break
    # Crossref fallback for conference proceedings OpenAlex leaves blank
    if not name and work.get("doi"):
        try:
            doi = work["doi"].replace("https://doi.org/", "")
            cr = http_json(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}")
            msg = (cr.get("message") or {})
            name = (msg.get("container-title") or [""])[0] or (msg.get("event") or {}).get("name", "")
            vtype = "proceedings" if msg.get("type") == "proceedings-article" else "journal"
        except Exception:
            pass
    return name.strip(), vtype


def authors_of(work: dict) -> tuple[list[str], int]:
    """Return (author list with 'me' placeholder, 1-based own position)."""
    out, pos = [], 0
    for i, a in enumerate(work.get("authorships") or [], start=1):
        name = (a.get("author") or {}).get("display_name", "").strip()
        if name.lower() in OWN_ALIASES or name.lower() == OWN_NAME.lower():
            out.append("me")
            pos = pos or i
        else:
            out.append(name)
    return out, pos


def coauthor_ok(work: dict) -> bool:
    names = {(a.get("author") or {}).get("display_name", "") for a in work.get("authorships") or []}
    return bool(names & COAUTHOR_WHITELIST)


def venue_meta(name: str, venues: dict) -> dict:
    meta = venues.get(name)
    if meta:
        return meta
    # case-insensitive / containment match
    low = name.lower()
    for key, val in venues.items():
        k = key.lower()
        if k and (k in low or low in k):
            return val
    return {}


def badges_for(venue: str, vtype: str, venues: dict) -> list[dict]:
    meta = venue_meta(venue, venues)
    badges = []
    ccf = meta.get("ccf")
    if ccf:
        badges.append({"name": f"CCF-{ccf}", "level": "featured"})
    if vtype != "proceedings" and vtype != "conference":
        cas = meta.get("cas") or ""
        if cas:
            badges.append({"name": f"中科院{cas}区", "level": "featured"})
        jcr = meta.get("jcr") or ""
        if jcr:
            badges.append({"name": f"JCR {jcr}", "level": "featured"})
    if not meta:
        print(f"  ! venue not in venues.yml, no badges: {venue!r}")
    return badges


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:80] or "paper"


def yaml_list(items: list[str], indent: str = "  ") -> str:
    return "\n".join(f"{indent}- {json.dumps(i, ensure_ascii=False)}" for i in items)


def build_page(work: dict, venues: dict) -> tuple[pathlib.Path, str]:
    title = (work.get("title") or work.get("display_name") or "").strip()
    authors, pos = authors_of(work)
    venue, vtype = venue_of(work)
    year = work.get("publication_year") or 0
    date = work.get("publication_date") or f"{year}-01-01"
    doi = (work.get("doi") or "").replace("https://doi.org/", "")
    arxiv = ((work.get("ids") or {}).get("mag") and "") or ""
    for loc in work.get("locations") or []:
        src = (loc.get("source") or {})
        if src.get("display_name", "").lower() == "arxiv":
            arxiv = (loc.get("landing_page_url") or "").split("/abs/")[-1]
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    ptype = "paper-conference" if (vtype in {"conference", "proceedings"} or "conference" in venue.lower() or "symposium" in venue.lower()) else "article-journal"
    folder_type = "conference-paper" if ptype == "paper-conference" else "journal-article"
    badges = badges_for(venue, vtype, venues)
    featured = (pos == 1) and (venue in FEATURED_VENUES)

    lines = [
        "---",
        "# ⚠️ GENERATED by scripts/sync_publications.py — do not edit by hand.",
        f"title: {json.dumps(title, ensure_ascii=False)}",
        "authors:",
        yaml_list(authors),
        f"author_position: {pos}",
        f"date: {date}",
        f"publishDate: {date}",
        f"publication_types: [{json.dumps(ptype)}]",
        "publication:",
        f"  name: {json.dumps(venue, ensure_ascii=False)}",
        "  year: " + str(year),
        "peer_reviewed: true",
        f"open_access: {'true' if (work.get('open_access') or {}).get('is_oa') else 'false'}",
        f"cited_by: {work.get('cited_by_count', 0)}",
        f"featured: {'true' if featured else 'false'}",
    ]
    if badges:
        lines.append("awards:")
        for b in badges:
            lines.append(f"  - name: {json.dumps(b['name'], ensure_ascii=False)}")
            lines.append(f"    level: {b['level']}")
    if doi:
        lines += ["hugoblox:", "  ids:", f"    doi: {doi}"]
    if arxiv:
        if "hugoblox" not in "\n".join(lines):
            lines += ["hugoblox:", "  ids:"]
        lines.append(f"    arxiv: {arxiv}")
    if doi or arxiv:
        lines.append("links:")
        if doi:
            lines += ["  - type: doi", f"    url: https://doi.org/{doi}"]
        if arxiv:
            lines += ["  - type: preprint", f"    url: https://arxiv.org/abs/{arxiv}"]
    if abstract:
        lines.append(f"abstract: {json.dumps(abstract[:1800], ensure_ascii=False)}")
        summary = re.split(r"(?<=[.!?])\s+", abstract)[:2]
        lines.append(f"summary: {json.dumps(' '.join(summary)[:400], ensure_ascii=False)}")
    lines += ["projects: []", 'slides: ""', "---", "", f"> {venue} ({year})", ""]
    if abstract:
        lines += [abstract, ""]

    slug = slugify(f"{year}-{title}")
    path = OUT_DIR / folder_type / slug / "index.md"
    return path, "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    venues = load_venues()
    works = fetch_works()
    print(f"OpenAlex returned {len(works)} works for ORCID {ORCID}")

    seen_dois, entries, skipped = set(), [], []
    for w in works:
        title = (w.get("title") or "").strip()
        if not title or EXCLUDE_TITLE_RE.match(title):
            skipped.append((title, "correction/errata"))
            continue
        venue, vtype = venue_of(w)
        if EXCLUDE_VENUE_RE.match(venue) and any(
            (o.get("doi") or "") for o in [w]
        ):
            skipped.append((title, "preprint duplicate"))
            continue
        if not coauthor_ok(w):
            skipped.append((title, "no whitelisted co-author (possible namesake)"))
            continue
        doi = (w.get("doi") or "").lower()
        key = doi or title.lower()
        if key in seen_dois:
            skipped.append((title, "duplicate"))
            continue
        seen_dois.add(key)
        entries.append(w)

    entries.sort(key=lambda w: (w.get("publication_date") or ""), reverse=True)
    print(f"\nkept {len(entries)} — writing pages…")
    written = []
    for w in entries:
        path, body = build_page(w, venues)
        written.append(path)
        if args.dry_run:
            print(f"  [dry-run] {path.relative_to(ROOT)}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
            print(f"  wrote {path.relative_to(ROOT)}")

    if not args.dry_run:
        keep = {p.parent for p in written}
        for old in OUT_DIR.rglob("index.md"):
            if "GENERATED by scripts/sync_publications.py" in old.read_text(encoding="utf-8", errors="ignore") and old.parent not in keep:
                print(f"  removed stale {old.relative_to(ROOT)}")
                old.unlink()
                if not any(old.parent.iterdir()):
                    old.parent.rmdir()

    if skipped:
        print("\nskipped:")
        for t, why in skipped:
            print(f"  - [{why}] {t[:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
