#!/usr/bin/env python3
"""生成可打印的 A4 简历（中英双语 → /cv/ 与 /cv/zh/，含 PDF）。

数据来源（单一来源，不在本文件里重复内容）
  英文版  data/authors/me.yaml                学历 / 经历 / 荣誉 / 技能 / 语言 / 链接
          data/cv_extra.yaml                  联系方式、研究概述、受邀报告、学术服务、教学、论文配置
  中文版  data/cv_zh.yaml                     同上各节的"中文表述"
  两版共用 content/publications/**/index.md   论文列表（题名保留英文原文）

用法
  python3 scripts/build_cv.py               # 生成两版 HTML
  python3 scripts/build_cv.py --pdf         # 同时用 headless chromium 渲染两版 PDF
  python3 scripts/build_cv.py --lang zh     # 只做中文版（en / zh / both，默认 both）
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
STATIC_CV = ROOT / "static" / "cv"
PHOTO = STATIC_CV / "photo.jpg"
SITE = "jianke-yu.online"

TARGETS: dict[str, dict] = {
    "en": {
        "html": STATIC_CV / "index.html",
        "pdf": STATIC_CV / "Jianke-Yu-CV.pdf",
        "dir": STATIC_CV,
        "photo": "photo.jpg",
        "html_lang": "en",
        "pdf_href": "Jianke-Yu-CV.pdf",
        "alt_href": "zh/",
    },
    "zh": {
        "html": STATIC_CV / "zh" / "index.html",
        "pdf": STATIC_CV / "zh" / "Jianke-Yu-CV-zh.pdf",
        "dir": STATIC_CV / "zh",
        "photo": "../photo.jpg",
        "html_lang": "zh-CN",
        "pdf_href": "Jianke-Yu-CV-zh.pdf",
        "alt_href": "../",
    },
}

LABELS: dict[str, dict[str, str]] = {
    "en": {
        "doctitle": "Curriculum Vitae",
        "print": "Print / Save as PDF",
        "download": "Download PDF",
        "switch": "中文版",
        "research": "Research Interests",
        "keywords": "Keywords:",
        "education": "Education",
        "appointments": "Appointments & Experience",
        "publications": "Publications",
        "talks": "Invited Talks",
        "honors": "Honors & Awards",
        "service": "Academic Service",
        "teaching": "Teaching",
        "skills": "Skills & Languages",
        "first_author": "1st author",
        "updated": "Updated",
        "full_list": "Full list",
        "present": "Present",
    },
    "zh": {
        "doctitle": "个人简历",
        "print": "打印 · 存为 PDF",
        "download": "下载 PDF",
        "switch": "English",
        "research": "研究兴趣",
        "keywords": "关键词：",
        "education": "教育经历",
        "appointments": "工作与科研经历",
        "publications": "论文发表",
        "talks": "学术报告",
        "honors": "荣誉与奖励",
        "service": "学术服务",
        "teaching": "教学工作",
        "skills": "技能与语言",
        "first_author": "第一作者",
        "updated": "更新于",
        "full_list": "完整列表",
        "present": "至今",
    },
}


# ---------------------------------------------------------------- helpers
def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def esc(text) -> str:
    return ht.escape(str(text if text is not None else ""), quote=True)


def clean(text) -> str:
    """把 YAML 块里的换行/多余空格压成一行。"""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def fmt_month(value) -> str:
    """'2023-07-01' / date -> '2023.07'；其他字符串原样返回。"""
    if not value:
        return ""
    if isinstance(value, datetime):
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
            if datetime.strptime(str(start)[:10], "%Y-%m-%d") > datetime.now():
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


PLACEHOLDER_SKIP = re.compile(r"(?i)(to be confirmed|tbd|待确认|待补)")

# 中文版里的徽章译名（论文 front matter 里是英文）
BADGE_ZH = {
    "CAS Zone 1 Top": "中科院 1 区 Top",
    "CAS Zone 2": "中科院 2 区",
    "CAS Zone 3": "中科院 3 区",
    "CAS Zone 4": "中科院 4 区",
}


def localize_badge(name: str, lang: str) -> str:
    return BADGE_ZH.get(name, name) if lang == "zh" else name


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
                "title": clean(fm.get("title")),
                "folder": md.parent.parent.name,
                "venue": clean(publication.get("name")),
                "year": year_of(publication.get("year") or fm.get("date")),
                "position": position,
                "types": fm.get("publication_types") or [],
                "badges": [
                    clean((b or {}).get("name"))
                    for b in (fm.get("awards") or [])
                    if clean((b or {}).get("name"))
                ],
                "featured": bool(fm.get("featured")),
                "cited_by": fm.get("cited_by"),
            }
        )
    return items


def pub_stats(items: list[dict]) -> dict:
    journals = sum(1 for i in items if i.get("folder") == "journal-article")
    conferences = sum(1 for i in items if i.get("folder") == "conference-paper")
    first_author = sum(1 for i in items if i["position"] == 1)
    ccf_a = sum(1 for i in items if any("CCF-A" in b for b in i["badges"]))
    citations = sum(int(i["cited_by"] or 0) for i in items)
    return {
        "total": len(items),
        "journals": journals,
        "conferences": conferences,
        "others": len(items) - journals - conferences,
        "first_author": first_author,
        "ccf_a": ccf_a,
        "citations": citations,
    }


# ---------------------------------------------------------------- content
def content_en() -> dict:
    me = load_yaml(ROOT / "data" / "authors" / "me.yaml")
    extra = load_yaml(ROOT / "data" / "cv_extra.yaml")
    name = me.get("name") or {}
    present = LABELS["en"]["present"]

    contact_cfg = extra.get("contact") or {}
    contact = [
        {"key": clean(i.get("key")), "label": clean(i.get("label")), "url": (i.get("url") or "").strip()}
        for i in (contact_cfg.get("items") or [])
    ]

    education = [
        {
            "t": clean(i.get("degree")),
            "s": clean(i.get("institution")),
            "w": fmt_period(i.get("start"), i.get("end"), present),
            "n": clean(i.get("summary")),
        }
        for i in me.get("education") or []
    ]
    experience = [
        {
            "t": clean(i.get("role")),
            "s": clean(i.get("org")),
            "w": fmt_period(i.get("start"), i.get("end"), present),
            "n": clean(i.get("summary")),
        }
        for i in me.get("experience") or []
    ]
    awards = []
    for i in me.get("awards") or []:
        note = clean(i.get("summary"))
        awards.append(
            {
                "t": clean(i.get("title")),
                "s": clean(i.get("awarder")),
                "w": year_of(i.get("date")),
                "n": "" if PLACEHOLDER_SKIP.search(note) else note,
            }
        )
    skills = [
        {
            "k": clean(g.get("name")),
            "v": ", ".join(clean(x.get("label")) for x in g.get("items") or []),
        }
        for g in me.get("skills") or []
    ]
    languages = ", ".join(
        f"{clean(l.get('name'))} ({clean(l.get('label'))})".replace(" ()", "")
        for l in me.get("languages") or []
    )

    return {
        "name": clean(name.get("display")),
        "alt": f"{clean(name.get('alternate'))}, {', '.join(me.get('postnominals') or [])}".strip(", "),
        "role": clean(me.get("role")),
        "location": clean(contact_cfg.get("location")),
        "contact": contact,
        "statement": clean(extra.get("research_statement")),
        "interests": ", ".join(clean(i) for i in me.get("interests") or []),
        "education": education,
        "experience": experience,
        "talks": [
            {"t": clean(i.get("title")), "s": clean(i.get("event")), "w": clean(i.get("date")), "n": ""}
            for i in extra.get("invited_talks") or []
        ],
        "awards": awards,
        "service": [
            {"t": clean(i.get("role")), "s": clean(i.get("org")), "w": clean(i.get("period")), "n": ""}
            for i in extra.get("academic_service") or []
        ],
        "teaching": [
            {"t": clean(i.get("role")), "s": clean(i.get("org")), "w": clean(i.get("period")), "n": ""}
            for i in extra.get("teaching") or []
        ],
        "skills": skills,
        "languages": languages,
        "pub_cfg": extra.get("publications") or {},
    }


def content_zh() -> dict:
    zh = load_yaml(ROOT / "data" / "cv_zh.yaml")
    name = zh.get("name") or {}

    def entries(key: str) -> list[dict]:
        return [
            {
                "t": clean(i.get("title")),
                "s": clean(i.get("sub")),
                "w": clean(i.get("when")),
                "n": "" if PLACEHOLDER_SKIP.search(clean(i.get("note"))) else clean(i.get("note")),
            }
            for i in zh.get(key) or []
        ]

    return {
        "name": clean(name.get("display")),
        "alt": f"{clean(name.get('alt'))}, {clean(name.get('postnominal'))}".strip(", "),
        "role": clean(zh.get("role")),
        "location": clean(zh.get("location")),
        "contact": [
            {"key": clean(i.get("key")), "label": clean(i.get("label")), "url": (i.get("url") or "").strip()}
            for i in zh.get("contact") or []
        ],
        "statement": clean(zh.get("research_statement")),
        "interests": clean(zh.get("interests")),
        "education": entries("education"),
        "experience": entries("experience"),
        "talks": entries("invited_talks"),
        "awards": entries("awards"),
        "service": entries("academic_service"),
        "teaching": entries("teaching"),
        "skills": [
            {"k": clean(i.get("key")), "v": clean(i.get("value"))} for i in zh.get("skills") or []
        ],
        "languages": clean(zh.get("languages")),
        "pub_cfg": load_yaml(ROOT / "data" / "cv_extra.yaml").get("publications") or {},
    }


# ---------------------------------------------------------------- rendering
CSS = """
@page { size: A4; margin: 11mm 13mm 10mm; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
:root {
  --navy: #123c69; --ink: #1c2126; --muted: #5b6779; --soft: #8794a5;
  --rule: #ccd8e6; --tint: #f2f7fc; --hair: #e3eaf3;
}
body {
  margin: 0 auto; background: #eef1f5; color: var(--ink);
  font-family: "Noto Sans", "Liberation Sans", Arial, sans-serif;
  font-size: 9.15pt; line-height: 1.33;
}
body[data-lang="zh-CN"] {
  font-family: "Noto Serif CJK SC", "Noto Serif SC", serif; line-height: 1.46;
}
body[data-lang="zh-CN"] h1, body[data-lang="zh-CN"] h2,
body[data-lang="zh-CN"] .t, body[data-lang="zh-CN"] .skill .k { font-family: "Noto Sans CJK SC", "Noto Sans SC", sans-serif; }
.sheet {
  width: 210mm; min-height: 297mm; margin: 9mm auto; padding: 12mm 14mm 10mm;
  background: #fff; box-shadow: 0 3px 18px rgba(15, 25, 40, .14);
}
a { color: var(--navy); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ---------- header ---------- */
header { display: flex; gap: 13px; align-items: flex-start; padding-bottom: 6px; border-bottom: 2px solid var(--navy); }
.photo img { width: 23.6mm; height: 31.5mm; object-fit: cover; display: block; border: 1px solid var(--rule); border-radius: 1.5px; }
.who { flex: 1 1 auto; min-width: 0; }
h1 { margin: 0; font-size: 19.5pt; line-height: 1.14; color: var(--navy); letter-spacing: .2px; }
h1 .alt { font-size: 11.5pt; font-weight: 500; color: #41505f; margin-left: 8px; letter-spacing: 0; }
.role { font-size: 10.3pt; font-weight: 600; color: var(--navy); margin-top: 2px; }
.where { font-size: 9pt; color: var(--soft); margin-top: 1px; }
.contact { margin-top: 5px; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px 10px; font-size: 8.8pt; }
.contact span { color: #3b4a5c; overflow-wrap: anywhere; }
.contact .k { color: var(--soft); margin-right: 3px; }

/* ---------- sections ---------- */
h2 {
  display: flex; align-items: center; gap: 6px; margin: 7.5px 0 4px;
  font-size: 10.05pt; font-weight: 700; letter-spacing: .9px; color: var(--navy);
  text-transform: uppercase; page-break-after: avoid; break-after: avoid;
}
h2 .bar { width: 3px; height: 10.5px; background: var(--navy); border-radius: 1px; }
h2 .rule { flex: 1 1 auto; height: 1px; background: var(--rule); }
body[data-lang="zh-CN"] h2 { font-size: 10.4pt; letter-spacing: .5px; text-transform: none; margin: 6.5px 0 3.5px; }

.entry { margin-bottom: 3.4px; page-break-inside: avoid; break-inside: avoid; }
.entry .row { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; }
.entry .t { font-weight: 700; }
.entry .s { color: var(--muted); font-weight: 400; }
.entry .w { color: #3b4a5c; white-space: nowrap; font-variant-numeric: tabular-nums; }
.entry .n { color: var(--muted); font-size: 9.05pt; margin-top: .6px; }

.pubstats { font-size: 9pt; color: var(--muted); margin: 0 0 5px; }
.pubs { list-style: none; margin: 0; padding: 0; }
/* 悬挂缩进：编号绝对定位在最左（不能用 flex —— 行内的 venue/badge 会被拆成 flex item；
   也不能用负 text-indent —— Chrome 打印时会把后续行的 inine-block 徽章叠在一起） */
.pubs li { position: relative; padding-left: 28px; margin-bottom: 2.9px; page-break-inside: avoid; break-inside: avoid; }
.pubs li .num { position: absolute; left: 0; top: 0; color: var(--navy); font-weight: 700; }
.venue { font-style: italic; }
.badge {
  display: inline-block; font-size: 7.4pt; font-weight: 600; line-height: 1.5;
  border: 1px solid #c3d2e3; background: var(--tint); color: var(--navy);
  border-radius: 9px; padding: 0 5px; margin-left: 4px; white-space: nowrap;
}
.badge.fa { background: var(--navy); border-color: var(--navy); color: #fff; }
.badge.ccf { border-color: var(--navy); background: #fff; color: var(--navy); font-weight: 700; }

.cols { display: grid; grid-template-columns: 1fr 1fr; column-gap: 16px; }
.cols > div + div { border-left: 1px solid var(--hair); padding-left: 16px; }
.w-inline { color: var(--soft); font-size: 8.8pt; white-space: nowrap; }

.skill { display: grid; grid-template-columns: 74px 1fr; gap: 8px; margin-bottom: 2.5px; }
body[data-lang="zh-CN"] .skill { grid-template-columns: 66px 1fr; }
.skill .k { font-weight: 700; color: var(--navy); }

.foot {
  margin-top: 10px; padding-top: 5px; border-top: 1px solid var(--hair);
  display: flex; justify-content: space-between; gap: 10px;
  color: var(--soft); font-size: 8.1pt;
}

/* ---------- toolbar (screen only) ---------- */
.toolbar {
  position: fixed; top: 10px; right: 12px; display: flex; gap: 8px; z-index: 9;
  font-family: "Noto Sans", "Noto Sans CJK SC", Arial, sans-serif; font-size: 9pt;
}
.toolbar button, .toolbar a {
  border: 1px solid var(--navy); color: var(--navy); background: #fff;
  border-radius: 5px; padding: 4px 10px; cursor: pointer; font: inherit; line-height: 1.6;
}
@media print {
  body { background: #fff; font-size: 9.5pt; }
  .sheet { width: auto; min-height: 0; margin: 0; padding: 0; box-shadow: none; }
  .toolbar { display: none !important; }
  a { color: inherit; }
}
"""


def h2(title: str) -> str:
    return f'<h2><span class="bar"></span>{esc(title)}<span class="rule"></span></h2>'


def entry_html(item: dict) -> str:
    sub = f'<span class="s"> · {esc(item["s"])}</span>' if item.get("s") else ""
    when = f'<div class="w">{esc(item["w"])}</div>' if item.get("w") else ""
    note = f'<div class="n">{esc(item["n"])}</div>' if item.get("n") else ""
    return (
        f'<div class="entry"><div class="row"><div class="t">{esc(item["t"])}{sub}</div>'
        f'{when}</div>{note}</div>'
    )


def entries_html(items: list[dict]) -> str:
    return "\n".join(entry_html(i) for i in items)


def entries_compact_html(items: list[dict]) -> str:
    """窄栏（双栏区块）用：日期跟在行内，避免标题被挤压成窄列。"""
    rows = []
    for item in items:
        sub = f'<span class="s"> · {esc(item["s"])}</span>' if item.get("s") else ""
        when = f' <span class="w-inline">{esc(item["w"])}</span>' if item.get("w") else ""
        note = f'<div class="n">{esc(item["n"])}</div>' if item.get("n") else ""
        rows.append(f'<div class="entry"><span class="t">{esc(item["t"])}</span>{sub}{when}{note}</div>')
    return "\n".join(rows)


def pubs_block(cfg: dict, lang: str) -> str:
    labels = LABELS[lang]
    items = load_publications()
    if not cfg.get("include_preprints", False):
        items = [i for i in items if i["folder"] != "preprint" and "preprint" not in i["types"]]
    if cfg.get("featured_first", True):
        ordered = sorted(items, key=lambda i: (not i["featured"], -int(i["year"] or 0)))
    else:
        ordered = sorted(items, key=lambda i: -int(i["year"] or 0))
    ordered = ordered[: int(cfg.get("max_items", 20))]

    stats = pub_stats(items)
    if lang == "zh":
        extra = f"，另有其他类型 {stats['others']} 篇" if stats["others"] else ""
        summary = (
            f"同行评审论文 {stats['total']} 篇（期刊 {stats['journals']} 篇、"
            f"会议 {stats['conferences']} 篇）{extra}，第一作者 {stats['first_author']} 篇，"
            f"CCF-A 类 {stats['ccf_a']} 篇，总被引 {stats['citations']} 次。"
        )
    else:
        extra = f", {stats['others']} other" if stats["others"] else ""
        summary = (
            f"{stats['total']} peer-reviewed papers ({stats['journals']} journal, "
            f"{stats['conferences']} conference{extra}), {stats['first_author']} as first author, "
            f"{stats['ccf_a']} CCF-A, {stats['citations']} citations."
        )

    rows = []
    for idx, item in enumerate(ordered, start=1):
        marks = f'<span class="badge fa">{esc(labels["first_author"])}</span>' if item["position"] == 1 else ""
        chips = ""
        for badge in sorted(item["badges"], key=lambda b: (not b.startswith("CCF-"), b)):
            css = "badge ccf" if badge.startswith("CCF-") else "badge"
            chips += f'<span class="{css}">{esc(localize_badge(badge, lang))}</span>'
        venue = f'<span class="venue">{esc(item["venue"])}</span>' if item["venue"] else ""
        tail = f", {esc(item['year'])}" if item["year"] else ""
        rows.append(
            f'<li><span class="num">[{idx}]</span>{esc(item["title"])}. {venue}{tail}.'
            f'{marks}{chips}</li>'
        )
    return f'<div class="pubstats">{esc(summary)}</div>\n<ul class="pubs">\n' + "\n".join(rows) + "\n</ul>"


def build_html(lang: str) -> str:
    cfg = TARGETS[lang]
    labels = LABELS[lang]
    data = content_en() if lang == "en" else content_zh()
    generated = datetime.now().strftime("%d %b %Y") if lang == "en" else datetime.now().strftime("%Y-%m-%d")

    contact = "".join(
        f'<span><span class="k">{esc(i["key"])}</span>'
        + (f'<a href="{esc(i["url"])}">{esc(i["label"])}</a>' if i["url"] else esc(i["label"]))
        + "</span>"
        for i in data["contact"]
    )

    photo = (
        f'<div class="photo"><img src="{esc(cfg["photo"])}" alt="{esc(data["name"])}"></div>'
        if PHOTO.exists()
        else ""
    )

    skills = "\n".join(
        f'<div class="skill"><div class="k">{esc(s["k"])}</div><div>{esc(s["v"])}</div></div>'
        for s in data["skills"]
    )
    if data["languages"]:
        lang_key = "语言" if lang == "zh" else "Languages"
        skills += f'\n<div class="skill"><div class="k">{lang_key}</div><div>{esc(data["languages"])}</div></div>'

    return f"""<!DOCTYPE html>
<!-- GENERATED by scripts/build_cv.py ({lang}) — 请勿手工编辑。
     数据来源：data/authors/me.yaml + data/cv_extra.yaml（英文）/
               data/cv_zh.yaml（中文）+ content/publications/**
     重新生成：python3 scripts/build_cv.py --pdf     生成日期 {generated} -->
<html lang="{esc(cfg['html_lang'])}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(data["name"])} — {esc(labels["doctitle"])}</title>
<meta name="description" content="{esc(labels['doctitle'])} of {esc(data['name'])} — graph machine learning and database systems.">
<style>{CSS}</style>
</head>
<body data-lang="{esc(cfg['html_lang'])}">
<div class="toolbar no-print">
  <button onclick="window.print()">{esc(labels["print"])}</button>
  <a href="{esc(cfg['pdf_href'])}">{esc(labels["download"])}</a>
  <a href="{esc(cfg['alt_href'])}">{esc(labels["switch"])}</a>
</div>
<div class="sheet">
  <header>
    {photo}
    <div class="who">
      <h1>{esc(data["name"])}<span class="alt">{esc(data["alt"])}</span></h1>
      <div class="role">{esc(data["role"])}</div>
      <div class="where">{esc(data["location"])}</div>
      <div class="contact">{contact}</div>
    </div>
  </header>

  {h2(labels["research"])}
  {f'<div class="entry"><div class="n">{esc(data["statement"])}</div></div>' if data["statement"] else ''}
  <div class="entry"><span class="t">{esc(labels["keywords"])}</span> {esc(data["interests"])}</div>

  {h2(labels["education"])}
  {entries_html(data["education"])}

  {h2(labels["appointments"])}
  {entries_html(data["experience"])}

  {h2(labels["publications"])}
  {pubs_block(data["pub_cfg"], lang)}

  {h2(labels["talks"])}
  {entries_html(data["talks"])}

  {h2(labels["honors"])}
  {entries_html(data["awards"])}

  <div class="cols">
    <div>
      {h2(labels["service"])}
      {entries_compact_html(data["service"])}
    </div>
    <div>
      {h2(labels["teaching"])}
      {entries_compact_html(data["teaching"])}
    </div>
  </div>

  {h2(labels["skills"])}
  {skills}

  <div class="foot">
    <span>{esc(labels["updated"])} {esc(generated)}</span>
    <span>{esc(labels["full_list"])}: {esc(SITE)}/publications</span>
  </div>
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


def build_pdf(lang: str) -> int:
    cfg = TARGETS[lang]
    chromium = find_chromium()
    if not chromium:
        print("[warn] 未找到 chromium，跳过 PDF（可用浏览器打开 /cv/ 自行打印）", file=sys.stderr)
        return 0
    cmd = [
        chromium, "--headless=new", "--no-sandbox", "--disable-gpu",
        "--no-pdf-header-footer", "--virtual-time-budget=8000",
        f"--print-to-pdf={cfg['pdf']}", cfg["html"].as_uri(),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not cfg["pdf"].exists():
        print(proc.stdout[-800:], proc.stderr[-800:], file=sys.stderr)
        return 1
    print(f"[pdf]  {cfg['pdf'].relative_to(ROOT)}  {cfg['pdf'].stat().st_size / 1024:.0f} KB")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 A4 可打印简历（en / zh）")
    parser.add_argument("--pdf", action="store_true", help="同时渲染 PDF")
    parser.add_argument("--lang", choices=("en", "zh", "both"), default="both", help="生成哪一版")
    args = parser.parse_args()

    if not PHOTO.exists():
        print(f"[warn] 缺少证件照 {PHOTO.relative_to(ROOT)}，简历头部将不显示照片", file=sys.stderr)

    langs = ("en", "zh") if args.lang == "both" else (args.lang,)
    rc = 0
    for lang in langs:
        cfg = TARGETS[lang]
        cfg["dir"].mkdir(parents=True, exist_ok=True)
        cfg["html"].write_text(build_html(lang), encoding="utf-8")
        print(f"[html] {cfg['html'].relative_to(ROOT)}  {cfg['html'].stat().st_size / 1024:.0f} KB")
        if args.pdf:
            rc |= build_pdf(lang)
    return rc


if __name__ == "__main__":
    sys.exit(main())
