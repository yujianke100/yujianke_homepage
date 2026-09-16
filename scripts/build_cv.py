#!/usr/bin/env python3
"""生成可打印的 A4 简历（网站 /cv/ 页面 + PDF）。

数据来源（单一来源，不在本文件里重复内容）
  data/authors/me.yaml             学历 / 经历 / 荣誉 / 技能 / 语言 / 链接
  data/cv_extra.yaml               联系方式行、研究概述、受邀报告、学术服务、教学
  content/publications/**/index.md 论文列表（front matter）

用法
  python3 scripts/build_cv.py          # 只写 static/cv/index.html
  python3 scripts/build_cv.py --pdf    # 同时用 headless chromium 渲染 static/cv/Jianke-Yu-CV.pdf
"""

from __future__ import annotations

import argparse
import html as ht
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "static" / "cv"
OUT_HTML = OUT_DIR / "index.html"
OUT_PDF = OUT_DIR / "Jianke-Yu-CV.pdf"

NAME_EN = "Jianke Yu"
NAME_CN = "俞鉴珂"
HOME_URL = "https://jianke-yu.online"


# ---------------------------------------------------------------- helpers
def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def esc(text) -> str:
    return ht.escape(str(text if text is not None else ""), quote=True)


def fmt_month(value) -> str:
    """'2023-07-01' / date -> '2023.07'；其他字符串原样返回。"""
    if not value:
        return ""
    if isinstance(value, (datetime,)):
        return f"{value.year}.{value.month:02d}"
    raw = str(value).strip()
    match = re.match(r"^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?$", raw)
    if match:
        return f"{match.group(1)}.{int(match.group(2)):02d}"
    return raw


def fmt_period(start, end, present: str = "Present") -> str:
    left, right = fmt_month(start), fmt_month(end)
    if not left and not right:
        return ""
    if left and not right:
        # 无结束时间：起算日在未来 = 尚未开始
        try:
            started = datetime.strptime(str(start)[:10], "%Y-%m-%d")
            if started > datetime.now():
                return f"{left} (incoming)"
        except ValueError:
            pass
        return f"{left} – {present}"
    return f"{left} – {right or present}"


def year_of(value) -> str:
    if not value:
        return ""
    match = re.search(r"(\d{4})", str(value))
    return match.group(1) if match else str(value)


def load_publications() -> list[dict]:
    """读取 content/publications/**/index.md 的 front matter。"""
    items: list[dict] = []
    for md in sorted((ROOT / "content" / "publications").glob("*/*/index.md")):
        text = md.read_text(encoding="utf-8", errors="ignore")
        match = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
        if not match:
            continue
        try:
            fm = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            continue
        publication = fm.get("publication") or {}
        authors = fm.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        position = fm.get("author_position")
        if position is None and authors:
            for idx, author in enumerate(authors, start=1):
                if str(author).strip().lower() == "me":
                    position = idx
                    break
        items.append(
            {
                "title": (fm.get("title") or "").strip(),
                "folder": md.parent.parent.name,
                "venue": (publication.get("name") or "").strip(),
                "year": year_of(publication.get("year") or fm.get("date")),
                "date": str(fm.get("date") or ""),
                "writers": ", ".join(str(a) for a in authors),
                "position": position,
                "types": fm.get("publication_types") or [],
                "badges": [
                    (b or {}).get("name", "")
                    for b in (fm.get("awards") or [])
                    if (b or {}).get("name")
                ],
                "featured": bool(fm.get("featured")),
                "cited_by": fm.get("cited_by"),
            }
        )
    return items


def pub_stats(items: list[dict]) -> dict:
    journals = sum(1 for i in items if i.get("folder") == "journal-article")
    conferences = sum(1 for i in items if i.get("folder") == "conference-paper")
    others = len(items) - journals - conferences
    first_author = sum(1 for i in items if i["position"] == 1)
    ccf_a = sum(1 for i in items if any("CCF-A" in b for b in i["badges"]))
    citations = sum(int(i["cited_by"] or 0) for i in items)
    return {
        "total": len(items),
        "journals": journals,
        "conferences": conferences,
        "others": others,
        "first_author": first_author,
        "ccf_a": ccf_a,
        "citations": citations,
    }


# ---------------------------------------------------------------- rendering
CSS = """
@page { size: A4; margin: 12mm 13mm 11mm; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  margin: 0 auto; background: #f4f5f7; color: #14181f;
  font-family: "Noto Sans", "Noto Sans CJK SC", "Liberation Sans", Arial, sans-serif;
  font-size: 9.4pt; line-height: 1.34;
}
.sheet {
  width: 210mm; min-height: 297mm; margin: 8mm auto; padding: 13mm 14mm 12mm;
  background: #fff; box-shadow: 0 2px 14px rgba(15, 25, 40, .16);
}
a { color: #0f4c81; text-decoration: none; }
a:hover { text-decoration: underline; }
header { border-bottom: 2px solid #14181f; padding-bottom: 5px; margin-bottom: 9px; }
h1 { font-size: 19pt; margin: 0; letter-spacing: .4px; }
h1 .cn { font-size: 12.5pt; font-weight: 500; color: #4a5361; margin-left: 7px; }
.role { font-size: 10.4pt; color: #0f4c81; font-weight: 600; margin-top: 2px; }
.contact { font-size: 8.9pt; color: #38414f; margin-top: 4px; }
.contact span.sep { color: #9aa4b2; margin: 0 4px; }
h2 {
  font-size: 10.2pt; text-transform: uppercase; letter-spacing: .9px;
  margin: 8.5px 0 4px; padding-bottom: 2px; border-bottom: 1px solid #c9d0da;
  page-break-after: avoid; break-after: avoid;
}
.entry { margin-bottom: 4.4px; page-break-inside: avoid; break-inside: avoid; }
.entry .line1 { display: flex; justify-content: space-between; gap: 8px; }
.entry .title { font-weight: 700; }
.entry .when { color: #4a5361; white-space: nowrap; font-variant-numeric: tabular-nums; }
.entry .sub { color: #38414f; }
.entry .note { color: #4a5361; font-size: 9.2pt; }
.entry.compact { margin-bottom: 3.6px; }
.when-inline { color: #6b7684; font-size: 8.9pt; }
ul.tight { margin: 2px 0 0; padding-left: 15px; }
ul.tight li { margin-bottom: 1px; }
.pubs { margin: 0; padding: 0; list-style: none; counter-reset: pub; }
.pubs li {
  margin-bottom: 3.6px; padding-left: 15px; position: relative;
  page-break-inside: avoid; break-inside: avoid;
}
.pubs li:before { content: "▪"; position: absolute; left: 2px; color: #0f4c81; }
.venue { font-style: italic; }
.badges { white-space: nowrap; }
.badge {
  display: inline-block; font-size: 7.6pt; font-weight: 600; letter-spacing: .2px;
  border: 1px solid #b9c3d1; border-radius: 3px; padding: 0 3.5px; margin-left: 3px;
  color: #33415a; background: #f2f5f9;
}
.badge.fa { border-color: #b45309; color: #92400e; background: #fef3e2; }
.star { color: #b45309; font-weight: 700; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.pubstats { font-size: 9.1pt; color: #4a5361; margin: -1px 0 5px; }
.toolbar {
  position: fixed; top: 10px; right: 12px; display: flex; gap: 8px;
  font-size: 9pt; z-index: 9;
}
.toolbar button, .toolbar a {
  border: 1px solid #0f4c81; color: #0f4c81; background: #fff; border-radius: 5px;
  padding: 4px 10px; cursor: pointer; font: inherit;
}
.toolbar a { line-height: 1.6; }
@media print {
  body { background: #fff; font-size: 9.6pt; }
  .sheet { width: auto; min-height: 0; margin: 0; padding: 0; box-shadow: none; }
  .toolbar { display: none !important; }
  a { color: #14181f; text-decoration: none; }
  h2 { margin-top: 9px; }
}
"""


def render_education(me: dict) -> str:
    rows = []
    for item in me.get("education") or []:
        when = fmt_period(item.get("start"), item.get("end"))
        note = (item.get("summary") or "").strip().replace("\n", " ")
        rows.append(
            f'<div class="entry"><div class="line1"><div class="title">{esc(item.get("degree"))}'
            f'<span class="sub"> · {esc(item.get("institution"))}</span></div>'
            f'<div class="when">{esc(when)}</div></div>'
            + (f'<div class="note">{esc(note)}</div>' if note else "")
            + "</div>"
        )
    return "\n".join(rows)


def render_experience(me: dict) -> str:
    rows = []
    for item in me.get("experience") or []:
        when = fmt_period(item.get("start"), item.get("end"))
        note = (item.get("summary") or "").strip().replace("\n", " ")
        rows.append(
            f'<div class="entry"><div class="line1"><div class="title">{esc(item.get("role"))}'
            f'<span class="sub"> · {esc(item.get("org"))}</span></div>'
            f'<div class="when">{esc(when)}</div></div>'
            + (f'<div class="note">{esc(note)}</div>' if note else "")
            + "</div>"
        )
    return "\n".join(rows)


def render_publications(items: list[dict], cfg: dict) -> tuple[str, str]:
    if not cfg.get("include_preprints", False):
        items = [
            i for i in items
            if i.get("folder") != "preprint" and "preprint" not in i["types"]
        ]
    if cfg.get("featured_first", True):
        ordered = sorted(
            items, key=lambda i: (not i["featured"], -int(i["year"] or 0))
        )
    else:
        ordered = sorted(items, key=lambda i: -int(i["year"] or 0))
    ordered = ordered[: int(cfg.get("max_items", 20))]

    stats = pub_stats(items)
    parts = [f"{stats['journals']} journal", f"{stats['conferences']} conference"]
    if stats["others"]:
        parts.append(f"{stats['others']} other")
    summary = (
        f"{stats['total']} peer-reviewed papers ({', '.join(parts)}), "
        f"{stats['first_author']} as first author, {stats['ccf_a']} CCF-A, "
        f"{stats['citations']} citations."
    )

    rows = []
    for item in ordered:
        marks = ""
        if item["position"] == 1:
            marks += ' <span class="star">⭐ first author</span>'
        badges = ""
        if item["badges"]:
            chips = []
            for badge in item["badges"]:
                css = "badge fa" if badge.startswith("CCF-A") else "badge"
                chips.append(f'<span class="{css}">{esc(badge)}</span>')
            badges = ' <span class="badges">' + "".join(chips) + "</span>"
        venue = f'<span class="venue">{esc(item["venue"])}</span>' if item["venue"] else ""
        tail = f", {esc(item['year'])}" if item["year"] else ""
        rows.append(
            f'<li>{esc(item["title"])}. {venue}{tail}.{marks}{badges}</li>'
        )
    return summary, "\n".join(rows)


PLACEHOLDER_SKIP = re.compile(r"(?i)(to be confirmed|tbd|待确认|待补)")


def render_compact(entries: list[dict] | None, role_key: str, org_key: str, period_key: str) -> str:
    """窄栏（双栏布局）用的紧凑格式：日期跟在行内，自然换行。"""
    rows = []
    for item in entries or []:
        period = (item.get(period_key) or "").strip()
        when = f' <span class="when-inline">{esc(period)}</span>' if period else ""
        rows.append(
            f'<div class="entry compact"><span class="title">{esc(item.get(role_key))}</span>'
            f'<span class="sub"> · {esc(item.get(org_key))}</span>{when}</div>'
        )
    return "\n".join(rows)


def render_simple(entries: list[dict] | None, role_key: str, org_key: str, period_key: str) -> str:
    rows = []
    for item in entries or []:
        period = esc(item.get(period_key) or "")
        rows.append(
            f'<div class="entry"><div class="line1">'
            f'<div class="title">{esc(item.get(role_key))}'
            f'<span class="sub"> · {esc(item.get(org_key))}</span></div>'
            f'<div class="when">{period}</div></div></div>'
        )
    return "\n".join(rows)


def render_awards(me: dict) -> str:
    rows = []
    for item in me.get("awards") or []:
        when = year_of(item.get("date"))
        note = (item.get("summary") or "").strip().replace("\n", " ")
        if PLACEHOLDER_SKIP.search(note):
            note = ""
        rows.append(
            f'<div class="entry"><div class="line1"><div class="title">{esc(item.get("title"))}'
            f'<span class="sub"> · {esc(item.get("awarder"))}</span></div>'
            f'<div class="when">{esc(when)}</div></div>'
            + (f'<div class="note">{esc(note)}</div>' if note else "")
            + "</div>"
        )
    return "\n".join(rows)


def build_html() -> str:
    me = load_yaml(ROOT / "data" / "authors" / "me.yaml")
    extra = load_yaml(ROOT / "data" / "cv_extra.yaml")
    publications = load_publications()

    author = me.get("name") or {}
    display = author.get("display") or NAME_EN
    cn = author.get("alternate") or NAME_CN
    postnominals = ", ".join(me.get("postnominals") or [])
    role = me.get("role") or ""

    contact_bits = []
    location = (extra.get("contact") or {}).get("location")
    if location:
        contact_bits.append(esc(location))
    for item in (extra.get("contact") or {}).get("items") or []:
        label, url = esc(item.get("label")), esc(item.get("url"))
        contact_bits.append(f'<a href="{url}">{label}</a>' if url else label)
    contact_line = '<span class="sep">·</span>'.join(f"<span>{b}</span>" for b in contact_bits)

    pub_summary, pub_rows = render_publications(publications, extra.get("publications") or {})
    interests = ", ".join(me.get("interests") or [])

    skills_html = []
    for group in me.get("skills") or []:
        labels = ", ".join(esc(i.get("label")) for i in group.get("items") or [])
        skills_html.append(f'<div class="entry"><span class="title">{esc(group.get("name"))}:</span> {labels}</div>')
    languages = ", ".join(
        f'{esc(l.get("name"))} ({esc(l.get("label") or "")})'.replace(" ()", "")
        for l in me.get("languages") or []
    )
    if languages:
        skills_html.append(f'<div class="entry"><span class="title">Languages:</span> {languages}</div>')

    statement = (extra.get("research_statement") or "").strip()
    generated = datetime.now().strftime("%Y-%m-%d")

    return f"""<!DOCTYPE html>
<!-- GENERATED by scripts/build_cv.py — 请勿手工编辑。
     数据来源：data/authors/me.yaml + data/cv_extra.yaml + content/publications/**
     重新生成：python3 scripts/build_cv.py --pdf   （生成日期 {generated}） -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(display)} — Curriculum Vitae</title>
<meta name="description" content="Curriculum Vitae of {esc(display)} ({esc(cn)}), PhD, graph machine learning and databases.">
<style>{CSS}</style>
</head>
<body>
<div class="toolbar no-print">
  <button onclick="window.print()">打印 / 存为 PDF</button>
  <a href="/cv/Jianke-Yu-CV.pdf">下载 PDF</a>
</div>
<div class="sheet">
  <header>
    <h1>{esc(display)}<span class="cn">{esc(cn)}{", " + esc(postnominals) if postnominals else ""}</span></h1>
    <div class="role">{esc(role)}</div>
    <div class="contact">{contact_line}</div>
  </header>

  <h2>Research Interests</h2>
  {f'<div class="entry">{esc(statement)}</div>' if statement else ''}
  <div class="entry"><span class="title">Keywords:</span> {esc(interests)}</div>

  <h2>Education</h2>
  {render_education(me)}

  <h2>Appointments &amp; Experience</h2>
  {render_experience(me)}

  <h2>Publications</h2>
  <div class="pubstats">{esc(pub_summary)}</div>
  <ul class="pubs">
{pub_rows}
  </ul>

  <h2>Invited Talks</h2>
  {render_simple(extra.get('invited_talks'), 'title', 'event', 'date')}

  <h2>Honors &amp; Awards</h2>
  {render_awards(me)}

  <div class="cols">
    <div>
      <h2>Academic Service</h2>
      {render_compact(extra.get('academic_service'), 'role', 'org', 'period')}
    </div>
    <div>
      <h2>Teaching</h2>
      {render_compact(extra.get('teaching'), 'role', 'org', 'period')}
    </div>
  </div>

  <h2>Skills</h2>
  {chr(10).join(skills_html)}
</div>
</body>
</html>
"""


# ---------------------------------------------------------------- pdf
def find_chromium() -> str | None:
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        path = shutil.which(name)
        if path:
            return path
    return None


def build_pdf() -> int:
    chromium = find_chromium()
    if not chromium:
        print("[warn] 未找到 chromium，跳过 PDF（可用浏览器打开 /cv/ 自行打印）", file=sys.stderr)
        return 0
    cmd = [
        chromium, "--headless=new", "--no-sandbox", "--disable-gpu",
        "--no-pdf-header-footer", "--virtual-time-budget=8000",
        f"--print-to-pdf={OUT_PDF}", OUT_HTML.as_uri(),
    ]
    print("[pdf]", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not OUT_PDF.exists():
        print(proc.stdout[-800:], proc.stderr[-800:], file=sys.stderr)
        return 1
    print(f"[pdf] {OUT_PDF.relative_to(ROOT)}  {OUT_PDF.stat().st_size / 1024:.0f} KB")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 A4 可打印简历")
    parser.add_argument("--pdf", action="store_true", help="同时渲染 PDF")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(build_html(), encoding="utf-8")
    print(f"[html] {OUT_HTML.relative_to(ROOT)}  {OUT_HTML.stat().st_size / 1024:.0f} KB")
    if args.pdf:
        return build_pdf()
    return 0


if __name__ == "__main__":
    sys.exit(main())
