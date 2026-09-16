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
        "publications": "Selected Publications (first-author CCF-A)",
        "talks": "Invited Talks",
        "honors": "Honors & Awards",
        "service": "Academic Service",
        "teaching": "Teaching",
        "skills": "Skills",
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
        "publications": "代表性论文（第一作者 CCF-A）",
        "talks": "学术报告",
        "honors": "荣誉与奖励",
        "service": "学术服务",
        "teaching": "教学工作",
        "skills": "技能",
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
    def has(item: dict, prefix: str) -> bool:
        return any(b.startswith(prefix) for b in item["badges"])

    journals = sum(1 for i in items if i.get("folder") == "journal-article")
    conferences = sum(1 for i in items if i.get("folder") == "conference-paper")
    return {
        "total": len(items),
        "journals": journals,
        "conferences": conferences,
        "others": len(items) - journals - conferences,
        "first_author": sum(1 for i in items if i["position"] == 1),
        "ccf_a": sum(1 for i in items if has(i, "CCF-A")),
        "ccf_b": sum(1 for i in items if has(i, "CCF-B")),
        "ccf_c": sum(1 for i in items if has(i, "CCF-C")),
        "q1": sum(1 for i in items if has(i, "JCR Q1")),
        "citations": sum(int(i["cited_by"] or 0) for i in items),
    }


def pub_summary(stats: dict, lang: str) -> str:
    """数量统计行：只讲 CCF 与 SCI 论文数量（用户要求）。"""
    if lang == "zh":
        return (
            f"总体：同行评审论文 {stats['total']} 篇（SCI 期刊 {stats['journals']} 篇，"
            f"其中 JCR Q1 {stats['q1']} 篇；会议 {stats['conferences']} 篇）—— "
            f"CCF-A {stats['ccf_a']} 篇、CCF-B {stats['ccf_b']} 篇、CCF-C {stats['ccf_c']} 篇；"
            f"第一作者 {stats['first_author']} 篇；总被引 {stats['citations']} 次。"
        )
    return (
        f"Overall: {stats['total']} peer-reviewed papers ({stats['journals']} SCI journal papers, "
        f"{stats['q1']} in JCR Q1; {stats['conferences']} conference papers) — "
        f"{stats['ccf_a']} CCF-A, {stats['ccf_b']} CCF-B, {stats['ccf_c']} CCF-C; "
        f"{stats['first_author']} as first author; {stats['citations']} citations."
    )


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
    experience = []
    for item in me.get("experience") or []:
        start = item.get("start")
        if start and not item.get("end"):
            # 起效日在未来（尚未入职的单位）不进简历
            try:
                if datetime.strptime(str(start)[:10], "%Y-%m-%d") > datetime.now():
                    continue
            except ValueError:
                pass
        experience.append(
            {
                "t": clean(item.get("role")),
                "s": clean(item.get("org")),
                "w": fmt_period(start, item.get("end"), present),
                "n": clean(item.get("summary")),
            }
        )
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
# 配色参照 RenderCV 的主题约定：正文用近黑（不用灰），主色只给姓名/小标题/链接/徽章；
# 日期、机构等次级信息用深灰 #2c353d，页脚等三级信息用 #47515c —— 都保证打印清晰。
CSS = """
@page { size: A4; margin: 11mm 13mm 10mm; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
:root {
  --navy: #0b3d69; --ink: #111418; --ink-2: #2c353d; --ink-3: #47515c;
  --rule: #b6c4d4; --hair: #dbe3ec; --tint: #eef4fa;
}
body {
  margin: 0 auto; background: #eef1f5; color: var(--ink);
  font-family: Inter, "Noto Sans", "Liberation Sans", Arial, sans-serif;
  font-size: 9.9pt; line-height: 1.4;
}
body[data-lang="zh-CN"] {
  font-family: "Noto Sans CJK SC", "Noto Sans SC", Inter, sans-serif;
  font-size: 10pt; line-height: 1.6;
}
.sheet {
  width: 210mm; min-height: 297mm; margin: 9mm auto; padding: 12mm 14mm 10mm;
  background: #fff; box-shadow: 0 3px 18px rgba(15, 25, 40, .14);
}
a { color: var(--navy); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ---------- header ---------- */
header { display: flex; gap: 14px; align-items: flex-start; padding-bottom: 7px; border-bottom: 2.2px solid var(--navy); }
.photo img { width: 23.6mm; height: 31.5mm; object-fit: cover; display: block; border: 1px solid var(--rule); border-radius: 1.5px; }
.who { flex: 1 1 auto; min-width: 0; }
h1 { margin: 0; font-size: 21pt; line-height: 1.14; color: var(--navy); font-weight: 700; letter-spacing: .1px; }
h1 .alt { font-size: 12pt; font-weight: 500; color: var(--ink-2); margin-left: 9px; letter-spacing: 0; }
.role { font-size: 10.8pt; font-weight: 600; color: var(--navy); margin-top: 2.5px; }
.where { font-size: 9.6pt; color: var(--ink-3); margin-top: 1px; }
.contact { margin-top: 5.5px; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1.5px 10px; font-size: 9.4pt; }
.contact span { color: var(--ink); overflow-wrap: anywhere; }
.contact .k { color: var(--ink-3); margin-right: 3px; }

/* ---------- sections ---------- */
h2 {
  display: flex; align-items: center; gap: 7px; margin: 8.5px 0 4.5px;
  font-size: 11pt; font-weight: 700; letter-spacing: 1px; color: var(--navy);
  text-transform: uppercase; page-break-after: avoid; break-after: avoid;
}
h2 .bar { width: 3.5px; height: 11.5px; background: var(--navy); border-radius: 1px; }
h2 .rule { flex: 1 1 auto; height: 1px; background: var(--rule); }
body[data-lang="zh-CN"] h2 { font-size: 11.4pt; letter-spacing: .5px; text-transform: none; margin: 7.5px 0 4px; }

.entry { margin-bottom: 4px; page-break-inside: avoid; break-inside: avoid; }
.entry .row { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; }
.entry .t { font-weight: 700; color: var(--ink); }
.entry .s { color: var(--ink-2); font-weight: 400; }
.entry .w { color: var(--ink-2); font-weight: 500; white-space: nowrap; font-variant-numeric: tabular-nums; }
.entry .n { color: var(--ink-2); font-size: 9.7pt; margin-top: .8px; }

.pubstats { font-size: 9.6pt; color: var(--ink-2); margin: 0 0 5.5px; }
.pubs { list-style: none; margin: 0; padding: 0; }
/* 悬挂缩进：编号绝对定位在最左（不能用 flex —— 行内的 venue/badge 会被拆成 flex item；
   也不能用负 text-indent —— Chrome 打印时会把后续行的 inline-block 徽章叠在文字上） */
.pubs li { position: relative; padding-left: 30px; margin-bottom: 3.6px; page-break-inside: avoid; break-inside: avoid; }
.pubs li .num { position: absolute; left: 0; top: 0; color: var(--navy); font-weight: 700; }
.venue { font-style: italic; color: var(--ink-2); }
.badge {
  display: inline-block; font-size: 7.9pt; font-weight: 600; line-height: 1.55;
  border: 1px solid #a8bcd2; background: var(--tint); color: var(--navy);
  border-radius: 9px; padding: 0 5.5px; margin-left: 4px; white-space: nowrap;
}
.badge.fa { background: var(--navy); border-color: var(--navy); color: #fff; }
.badge.ccf { border-color: var(--navy); background: #fff; color: var(--navy); font-weight: 700; }

.cols { display: grid; grid-template-columns: 1fr 1fr; column-gap: 16px; }
.cols > div + div { border-left: 1px solid var(--hair); padding-left: 16px; }
.w-inline { color: var(--ink-2); font-size: 9.4pt; white-space: nowrap; }

.skill { display: grid; grid-template-columns: 84px 1fr; gap: 8px; margin-bottom: 3px; }
body[data-lang="zh-CN"] .skill { grid-template-columns: 72px 1fr; }
.skill .k { font-weight: 700; color: var(--navy); }

.foot {
  margin-top: 11px; padding-top: 5px; border-top: 1px solid var(--hair);
  display: flex; justify-content: space-between; gap: 10px;
  color: var(--ink-3); font-size: 8.8pt;
}
.page-break { break-before: page; page-break-before: always; }

/* ---------- toolbar (screen only) ---------- */
.toolbar {
  position: fixed; top: 10px; right: 12px; display: flex; gap: 8px; z-index: 9;
  font-family: Inter, "Noto Sans", "Noto Sans CJK SC", Arial, sans-serif; font-size: 9pt;
}
.toolbar button, .toolbar a {
  border: 1px solid var(--navy); color: var(--navy); background: #fff;
  border-radius: 5px; padding: 4px 10px; cursor: pointer; font: inherit; line-height: 1.6;
}
@media print {
  body { background: #fff; font-size: 10pt; }
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

    # 列哪些论文：mode = first_author_ccf_a（只列一作 CCF-A）/ first_author / all
    mode = str(cfg.get("mode", "all"))
    if mode == "first_author_ccf_a":
        ordered = [i for i in items if i["position"] == 1 and any(b.startswith("CCF-A") for b in i["badges"])]
    elif mode == "first_author":
        ordered = [i for i in items if i["position"] == 1]
    else:
        ordered = list(items)
    if cfg.get("featured_first", True):
        ordered = sorted(ordered, key=lambda i: (not i["featured"], -int(i["year"] or 0)))
    else:
        ordered = sorted(ordered, key=lambda i: -int(i["year"] or 0))
    ordered = ordered[: int(cfg.get("max_items", 20))]

    # 统计行永远统计全部同行评审论文（不受上面的筛选影响）
    summary = pub_summary(pub_stats(items), lang)

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
    page_break = '<div class="page-break"></div>' if data["pub_cfg"].get("page_break_before") else ""

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

  {page_break}
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
