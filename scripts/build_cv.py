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
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
STATIC_CV = ROOT / "static" / "cv"
PHOTO = STATIC_CV / "photo.jpg"
SITE = "jianke-yu.online"
# 论文条目作者行里本人的写法：与其它作者保持一致，统一用英文名（中文版也一样）
AUTHOR_LINE_NAME = "Jianke Yu"

TARGETS: dict[str, dict] = {
    "en": {
        "html": STATIC_CV / "index.html",
        "pdf": STATIC_CV / "Jianke-Yu-CV.pdf",
        "dir": STATIC_CV,
        "photo": "photo.jpg",
        "html_lang": "en",
        "pdf_href": "Jianke-Yu-CV.pdf",
        "alt_href": "zh/",
        "pubs_href": "publications/",
        "kind": "cv",
    },
    "zh": {
        "html": STATIC_CV / "zh" / "index.html",
        "pdf": STATIC_CV / "zh" / "Jianke-Yu-CV-zh.pdf",
        "dir": STATIC_CV / "zh",
        "photo": "../photo.jpg",
        "html_lang": "zh-CN",
        "pdf_href": "Jianke-Yu-CV-zh.pdf",
        "alt_href": "../",
        "pubs_href": "publications/",
        "kind": "cv",
    },
    # 完整论文列表（与简历同版式）：/cv/publications/ 与 /cv/zh/publications/
    "pubs_en": {
        "html": STATIC_CV / "publications" / "index.html",
        "pdf": STATIC_CV / "publications" / "Jianke-Yu-Publications.pdf",
        "dir": STATIC_CV / "publications",
        "photo": "../photo.jpg",
        "html_lang": "en",
        "pdf_href": "Jianke-Yu-Publications.pdf",
        "alt_href": "../zh/publications/",
        "cv_href": "../",
        "lang": "en",
        "kind": "pubs",
    },
    "pubs_zh": {
        "html": STATIC_CV / "zh" / "publications" / "index.html",
        "pdf": STATIC_CV / "zh" / "publications" / "Jianke-Yu-Publications-zh.pdf",
        "dir": STATIC_CV / "zh" / "publications",
        "photo": "../../photo.jpg",
        "html_lang": "zh-CN",
        "pdf_href": "Jianke-Yu-Publications-zh.pdf",
        "alt_href": "../../publications/",
        "cv_href": "../../zh/",
        "lang": "zh",
        "kind": "pubs",
    },
    # 工商入职专用：中文、按推荐表筛 A+ 及以上 + 署名角色限定
    "core_zh": {
        "html": STATIC_CV / "zh" / "publications-core" / "index.html",
        "pdf": STATIC_CV / "zh" / "publications-core" / "Jianke-Yu-Core-Publications-zh.pdf",
        "dir": STATIC_CV / "zh" / "publications-core",
        "photo": "../../photo.jpg",
        "html_lang": "zh-CN",
        "pdf_href": "Jianke-Yu-Core-Publications-zh.pdf",
        "alt_href": "../publications/",
        "cv_href": "../../zh/",
        "lang": "zh",
        "kind": "core",
    },
}

LABELS: dict[str, dict[str, str]] = {
    "en": {
        "doctitle": "Curriculum Vitae",
        "print": "Print / Save as PDF",
        "download": "Download PDF",
        "switch": "中文版",
        "research": "Research Areas",
        "keywords": "Keywords:",
        "education": "Education",
        "appointments": "Appointments & Experience",
        "publications": "Selected Publications (first-author CCF-A)",
        "talks": "Invited Talks",
        "honors": "Honors & Awards",
        "scholarships": "Scholarships & Funding",
        "activities": "Academic Activities & Service",
        "service": "Academic Service",
        "teaching": "Teaching",
        "skills": "Skills",
        "first_author": "1st author",
        # —— 完整论文列表页（/cv/publications/）——
        "pubs_doctitle": "Publication List",
        "pubs_intro": "Full list of peer-reviewed publications and preprints.",
        "pubs_button": "Publications",
        "journals": "Journal Articles",
        "conferences": "Conference Papers",
        "preprints": "Preprints",
        "citations": "citations",
        "featured": "Featured",
        "back_cv": "← CV",
        "updated": "Updated",
        "full_list": "Full list",
        "present": "Present",
    },
    "zh": {
        "doctitle": "个人简历",
        "print": "打印 · 存为 PDF",
        "download": "下载 PDF",
        "switch": "English",
        "research": "研究方向",
        "keywords": "关键词：",
        "education": "教育经历",
        "appointments": "工作与科研经历",
        "publications": "代表性论文（第一作者 CCF-A）",
        "talks": "学术报告",
        "honors": "荣誉与奖励",
        "scholarships": "奖学金与资助",
        "activities": "学术活动",
        "service": "学术服务",
        "teaching": "教学工作",
        "skills": "技能",
        "first_author": "第一作者",
        # —— 完整论文列表页（/cv/zh/publications/）——
        "pubs_doctitle": "论文列表",
        "pubs_intro": "同行评审论文与预印本完整列表。",
        "pubs_button": "完整论文列表",
        "journals": "期刊论文",
        "conferences": "会议论文",
        "preprints": "预印本",
        "citations": "被引",
        "featured": "代表论文",
        "back_cv": "← 简历",
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


# ---------------------------------------------------------------- github 星标
GH_CACHE = ROOT / "data" / ".cache_github.json"
_GH_STARS: dict[str, int | None] = {}


def github_stars(user: str) -> int | None:
    """自有仓库（排除 fork）的 star 合计；结果写缓存，API 失败时用缓存值。"""
    if user in _GH_STARS:
        return _GH_STARS[user]

    cache: dict = {}
    if GH_CACHE.exists():
        try:
            cache = json.loads(GH_CACHE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cache = {}

    stars: int | None = None
    try:
        req = urllib.request.Request(
            f"https://api.github.com/users/{user}/repos?per_page=100&type=owner",
            headers={"User-Agent": "build_cv", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=10) as fh:
            data = json.load(fh)
        if isinstance(data, list):
            own = [r for r in data if not r.get("fork")]
            stars = sum(int(r.get("stargazers_count") or 0) for r in own)
            cache[user] = {
                "stars": stars,
                "repos": len(own),
                "fetched": datetime.now().strftime("%Y-%m-%d"),
            }
            GH_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"[gh]   {user}: {stars} stars（{len(own)} 个自有仓库）")
    except Exception as exc:  # noqa: BLE001 — 网络/限流都可能失败，回退缓存
        print(f"[warn] GitHub star 获取失败（{exc}），改用缓存值", file=sys.stderr)
        got = (cache.get(user) or {}).get("stars")
        stars = int(got) if got is not None else None

    _GH_STARS[user] = stars
    return stars


def apply_github_stars(items: list[dict], cfg: dict) -> list[dict]:
    """给 GitHub 那条联系方式后面加上“（N ★）”。"""
    if not cfg.get("show_stars"):
        return items
    stars = github_stars(str(cfg.get("user") or "yujianke100"))
    if stars is None:
        return items
    for item in items:
        if "github.com" in str(item.get("url", "")):
            item["label"] = f'{item["label"]} ({stars} ★)'
    return items


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
                "authors": [clean(a) for a in authors],
                "doi": ((fm.get("hugoblox") or {}).get("ids") or {}).get("doi") or "",
                "arxiv": ((fm.get("hugoblox") or {}).get("ids") or {}).get("arxiv") or "",
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
    contact = apply_github_stars(contact, extra.get("github") or {})

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
    scholarship_titles = {
        clean(t) for t in ((extra.get("awards_split") or {}).get("scholarships") or [])
    }
    awards: list[dict] = []
    scholarships: list[dict] = []
    for i in me.get("awards") or []:
        note = clean(i.get("summary"))
        entry = {
            "t": clean(i.get("title")),
            "s": clean(i.get("awarder")),
            "w": year_of(i.get("date")),
            "n": "" if PLACEHOLDER_SKIP.search(note) else note,
        }
        (scholarships if entry["t"] in scholarship_titles else awards).append(entry)
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
            {"t": clean(i.get("title")), "s": clean(i.get("event")), "w": clean(i.get("date")), "n": clean(i.get("note"))}
            for i in extra.get("invited_talks") or []
        ],
        "awards": awards,
        "scholarships": scholarships,
        "service": [
            {"t": clean(i.get("role")), "s": clean(i.get("org")), "w": clean(i.get("period")), "n": clean(i.get("note"))}
            for i in extra.get("academic_service") or []
        ],
        "teaching": [
            {"t": clean(i.get("role")), "s": clean(i.get("org")), "w": clean(i.get("period")), "n": clean(i.get("note"))}
            for i in extra.get("teaching") or []
        ],
        "skills": skills,
        "languages": languages,
        "sections": extra.get("sections") or {},
        "pub_cfg": extra.get("publications") or {},
    }


def content_zh() -> dict:
    zh = load_yaml(ROOT / "data" / "cv_zh.yaml")
    extra = load_yaml(ROOT / "data" / "cv_extra.yaml")
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
        "contact": apply_github_stars(
            [
                {"key": clean(i.get("key")), "label": clean(i.get("label")), "url": (i.get("url") or "").strip()}
                for i in zh.get("contact") or []
            ],
            extra.get("github") or {},
        ),
        "statement": clean(zh.get("research_statement")),
        "interests": clean(zh.get("interests")),
        "education": entries("education"),
        "experience": entries("experience"),
        "talks": entries("invited_talks"),
        "awards": entries("awards"),
        "scholarships": entries("scholarships"),
        "service": entries("academic_service"),
        "teaching": entries("teaching"),
        "skills": [
            {"k": clean(i.get("key")), "v": clean(i.get("value"))} for i in zh.get("skills") or []
        ],
        "languages": clean(zh.get("languages")),
        "sections": extra.get("sections") or {},
        "pub_cfg": extra.get("publications") or {},
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
  font-size: 11.5pt; line-height: 1.46;
}
body[data-lang="zh-CN"] {
  font-family: "Noto Sans CJK SC", "Noto Sans SC", Inter, sans-serif;
  font-size: 11.5pt; line-height: 1.66;
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
.contact { margin-top: 5.5px; font-size: 9.4pt; color: var(--ink); }
.contact span { white-space: nowrap; }
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
.pubs li { position: relative; padding-left: 34px; margin-bottom: 3.6px; page-break-inside: avoid; break-inside: avoid; }
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

/* ---------- 完整论文列表页（/cv/publications/）---------- */
.pubs-full li { margin-bottom: 5px; }
body[data-lang="zh-CN"] .pubs-full li { margin-bottom: 4px; line-height: 1.5; }
body[data-lang="zh-CN"] .pubstats, body[data-lang="zh-CN"] .group-note { line-height: 1.45; }
body[data-lang="zh-CN"] .pubs-full .pauth, body[data-lang="zh-CN"] .pubs-full .pmeta { line-height: 1.42; }
.ptitle { font-weight: 700; }
.pauth { color: var(--ink-2); font-size: 9.3pt; margin-top: .6px; }
.pmeta { margin-top: 1.4px; }
.pmeta .badge { margin-left: 0; margin-right: 4px; }
.cite { color: var(--ink-3); font-size: 8.6pt; margin-left: 8px; }
.plink { font-size: 8.6pt; color: var(--navy); border-bottom: .5px solid var(--rule); margin-left: 7px; }
.badge.feat { background: #fff; border-color: var(--navy); color: var(--navy); font-weight: 600; }
.group-note { font-size: 9pt; color: var(--ink-3); margin: -2.5px 0 4.5px; }

/* ---------- 工商入职版：署名角色标签 ---------- */
.tag {
  display: inline-block; font-size: 7.9pt; font-weight: 700; line-height: 1.55;
  border: 1px solid var(--navy); background: var(--navy); color: #fff;
  border-radius: 3px; padding: 0 5px; margin-right: 4px; white-space: nowrap;
}
.tag.sec { background: #fff; color: var(--navy); }
.criteria { font-size: 9.3pt; color: var(--ink-2); line-height: 1.5; margin: 0 0 6px; }
.criteria b { color: var(--ink); }
.legend { font-size: 8.8pt; color: var(--ink-3); margin: 0 0 6px; line-height: 1.45; }

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
            f'<li><span class="num">[{idx}]</span> {esc(item["title"])}. {venue}{tail}.'
            f'{marks}{chips}</li>'
        )
    return f'<div class="pubstats">{esc(summary)}</div>\n<ul class="pubs">\n' + "\n".join(rows) + "\n</ul>"


# ------------------------------------------- 完整论文列表页（与简历同版式）
def pubs_page_summary(stats: dict, lang: str) -> str:
    peer = stats["total"] - stats["others"]
    if lang == "zh":
        extra = f"，另有预印本 {stats['others']} 篇" if stats["others"] else ""
        return (
            f"同行评审论文 {peer} 篇（SCI 期刊 {stats['journals']} 篇，其中 JCR Q1 {stats['q1']} 篇；"
            f"会议 {stats['conferences']} 篇）{extra} —— CCF-A {stats['ccf_a']} 篇、CCF-B {stats['ccf_b']} 篇、"
            f"CCF-C {stats['ccf_c']} 篇；第一作者 {stats['first_author']} 篇；总被引 {stats['citations']} 次。"
        )
    extra = f", plus {stats['others']} preprint" if stats["others"] else ""
    return (
        f"{peer} peer-reviewed papers ({stats['journals']} SCI journal papers, {stats['q1']} in JCR Q1; "
        f"{stats['conferences']} conference papers){extra} — {stats['ccf_a']} CCF-A, {stats['ccf_b']} CCF-B, "
        f"{stats['ccf_c']} CCF-C; {stats['first_author']} first-author; {stats['citations']} citations."
    )


def pub_authors_html(item: dict, me_name: str) -> str:
    out = []
    for author in item.get("authors") or []:
        if str(author).strip().lower() == "me":
            out.append(f"<b>{esc(me_name)}</b>")
        else:
            out.append(esc(author))
    return ", ".join(out)


def pub_links_html(item: dict) -> str:
    links = ""
    if item.get("doi"):
        links += f'<a class="plink" href="https://doi.org/{esc(item["doi"])}">DOI</a>'
    if item.get("arxiv"):
        links += f'<a class="plink" href="https://arxiv.org/abs/{esc(item["arxiv"])}">arXiv</a>'
    return links


def pub_list_rows(items: list[dict], lang: str, labels: dict, me_name: str, start: int = 1) -> tuple[str, int]:
    """整列表条目：编号 + 标题/期刊/年份 + 作者 + 徽章/DOI/被引。返回 (html, 下一个可用编号)。"""
    rows: list[str] = []
    for offset, item in enumerate(items):
        idx = start + offset
        marks = f'<span class="badge fa">{esc(labels["first_author"])}</span>' if item["position"] == 1 else ""
        if item.get("featured"):
            marks += f'<span class="badge feat">{esc(labels["featured"])}</span>'
        chips = ""
        for badge in sorted(item["badges"], key=lambda b: (not b.startswith("CCF-"), b)):
            css = "badge ccf" if badge.startswith("CCF-") else "badge"
            chips += f'<span class="{css}">{esc(localize_badge(badge, lang))}</span>'
        cites = int(item.get("cited_by") or 0)
        cite = f'<span class="cite">{cites} {esc(labels["citations"])}</span>' if cites else ""
        venue = f'<span class="venue">{esc(item["venue"])}</span>' if item["venue"] else ""
        tail = f", {esc(item['year'])}" if item["year"] else ""
        rows.append(
            f'<li><span class="num">[{idx}]</span> <span class="ptitle">{esc(item["title"])}</span>. '
            f"{venue}{tail}."
            f'<div class="pauth">{pub_authors_html(item, me_name)}</div>'
            f'<div class="pmeta">{marks}{chips}{pub_links_html(item)}{cite}</div></li>'
        )
    return "\n".join(rows), start + len(items)


def page_header_html(cfg: dict, data: dict) -> str:
    """与简历完全一致的头部（照片 + 姓名 + 角色 + 联系方式）。"""
    contact = " · ".join(
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
    return (
        "<header>\n    " + photo + '\n    <div class="who">\n'
        f'      <h1>{esc(data["name"])}<span class="alt">{esc(data["alt"])}</span></h1>\n'
        f'      <div class="role">{esc(data["role"])}</div>\n'
        f'      <div class="where">{esc(data["location"])}</div>\n'
        f'      <div class="contact">{contact}</div>\n'
        "    </div>\n  </header>"
    )


def build_publications_html(lang: str) -> str:
    cfg = TARGETS[f"pubs_{lang}"]
    labels = LABELS[lang]
    data = content_en() if lang == "en" else content_zh()
    generated = datetime.now().strftime("%d %b %Y") if lang == "en" else datetime.now().strftime("%Y-%m-%d")

    items = load_publications()
    by_type = {
        "journals": [i for i in items if i["folder"] == "journal-article"],
        "conferences": [i for i in items if i["folder"] == "conference-paper"],
    }
    by_type["preprints"] = [
        i for i in items if i["folder"] not in ("journal-article", "conference-paper")
    ]

    def order(seq: list[dict]) -> list[dict]:
        return sorted(seq, key=lambda i: (not i["featured"], -int(i["year"] or 0), i["title"]))

    indexed = 1
    groups_html = ""
    for key in ("journals", "conferences", "preprints"):
        group = order(by_type[key])
        if not group:
            continue
        rows, indexed = pub_list_rows(group, lang, labels, AUTHOR_LINE_NAME, start=indexed)
        groups_html += f'\n  {h2(labels[key])}\n  <ul class="pubs pubs-full">\n{rows}\n  </ul>\n'

    summary = pubs_page_summary(pub_stats(items), lang)
    intro = {
        "en": "This page lists all publications. The CV shows only the four selected first-author CCF-A papers.",
        "zh": "本页为完整列表；简历上只列第一作者 CCF-A 的 4 篇代表性论文。",
    }[lang]

    return f"""<!DOCTYPE html>
<!-- GENERATED by scripts/build_cv.py (pubs-{lang}) — 请勿手工编辑。
     数据来源：content/publications/**（scripts/sync_publications.py 自动同步）
     重新生成：python3 scripts/build_cv.py --pdf     生成日期 {generated} -->
<html lang="{esc(cfg['html_lang'])}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(data["name"])} — {esc(labels["pubs_doctitle"])}</title>
<meta name="description" content="{esc(labels['pubs_doctitle'])} of {esc(data['name'])}.">
<style>{CSS}</style>
</head>
<body data-lang="{esc(cfg['html_lang'])}">
<div class="toolbar no-print">
  <button onclick="window.print()">{esc(labels["print"])}</button>
  <a href="{esc(cfg['pdf_href'])}">{esc(labels["download"])}</a>
  <a href="{esc(cfg['cv_href'])}">{esc(labels["back_cv"])}</a>
  <a href="{esc(cfg['alt_href'])}">{esc(labels["switch"])}</a>
</div>
<div class="sheet">
  {page_header_html(cfg, data)}

  {h2(labels["pubs_doctitle"])}
  <div class="pubstats">{esc(summary)}</div>
  <div class="group-note">{esc(intro)}</div>
{groups_html}
  <div class="foot">
    <span>{esc(labels["updated"])} {esc(generated)}</span>
    <span>{esc(data["name"])} · {esc(SITE)}/cv/publications/</span>
  </div>
</div>
</body>
</html>
"""


# ------------------------ 工商入职版：按《刊物推荐表》筛 A+ 及以上 + 署名角色打标
CORE_MIN_YEAR = 2021


def load_venue_ratings() -> dict[str, dict]:
    data = load_yaml(ROOT / "data" / "venue_ratings.yml")
    out: dict[str, dict] = {}
    for kind in ("journals", "conferences"):
        for name, meta in (data.get(kind) or {}).items():
            out[str(name)] = dict(meta or {})
    return out


def load_roles() -> dict:
    return load_yaml(ROOT / "data" / "publication_roles.yml")


def rate_of(venue: str, ratings: dict[str, dict]) -> dict:
    """先精确匹配，再互相包含匹配（推荐表里的名字可能比 OpenAlex 略短/略长）。"""
    if venue in ratings:
        return ratings[venue]
    low = venue.lower()
    for name, meta in ratings.items():
        n = name.lower()
        if n and (n in low or low in n):
            return meta
    return {"rating": None, "ccf": None, "in_table": False, "note": "推荐表未收录"}


def role_tags(item: dict, roles: dict) -> list[str]:
    """按署名位置 + 通讯作者标注 + 人工标签，得出该论文的角色标签。"""
    supervisors = set(roles.get("supervisors") or [])
    info = (roles.get("papers") or {}).get(item.get("doi") or "", {}) or {}
    tags: list[str] = []
    if item["position"] == 1:
        tags.append("一作")
    if "Jianke Yu" in (info.get("corresponding") or []):
        tags.append("通讯作者")
    authors = item.get("authors") or []
    if item["position"] == 2 and authors and authors[0] in supervisors:
        tags.append("导师一作·学生二作")
    for tag in info.get("manual_tags") or []:
        if tag not in tags:
            tags.append(tag)
    return tags


def prepare_core_items() -> tuple[list[dict], list[dict], list[dict]]:
    """返回 (主表, 其他已发表, 预印本)。后两者每条都带 exclude_reason。"""
    ratings = load_venue_ratings()
    roles = load_roles()
    items = load_publications()
    for item in items:
        meta = rate_of(item["venue"], ratings)
        item["rating"] = meta.get("rating")
        item["ccf"] = meta.get("ccf")
        item["rate_note"] = meta.get("note") or ""
        item["tags"] = role_tags(item, roles)
        item["year_int"] = int(item["year"] or 0)
        item["long_paper"] = "extended abstract" not in item["title"].lower()
        item["a_plus"] = str(item["rating"] or "").startswith("A+")
        # 预印本（arXiv 等）单独成段，不与已发表论文混排
        item["is_preprint"] = item["folder"] not in ("journal-article", "conference-paper")

        if item["is_preprint"]:
            reason = "预印本（未正式发表）"
        elif item["year_int"] < CORE_MIN_YEAR:
            reason = f"{CORE_MIN_YEAR} 年前发表"
        elif not item["a_plus"]:
            reason = "推荐指数未达 A+（推荐表未收录）"
        elif not item["long_paper"]:
            reason = "会议短文（Extended Abstract）不计入"
        elif not item["tags"]:
            reason = f"署名角色不符合（本人为第 {item['position']} 作者）"
        else:
            reason = ""
        item["exclude_reason"] = reason

    def order(seq: list[dict]) -> list[dict]:
        return sorted(seq, key=lambda i: (not i["featured"], -i["year_int"], i["title"]))

    main = order([i for i in items if not i["exclude_reason"]])
    others = order([i for i in items if i["exclude_reason"] and not i["is_preprint"]])
    preprints = order([i for i in items if i["exclude_reason"] and i["is_preprint"]])
    return main, others, preprints


def core_rows_html(items: list[dict], me_name: str, start: int = 1, with_note: bool = False) -> str:
    rows: list[str] = []
    for offset, item in enumerate(items):
        idx = start + offset
        tags = ""
        if not with_note:  # 「其他（未计入）」段落不再显示署名标签，避免看起来像计入了
            tags = "".join(f'<span class="tag">{esc(t)}</span>' for t in item.get("tags") or [])
        rate = f'<span class="badge ccf">{esc(item["rating"])}</span>' if item.get("rating") else ""
        chips = ""
        for badge in sorted(item["badges"], key=lambda b: (not b.startswith("CCF-"), b)):
            css = "badge ccf" if badge.startswith("CCF-") else "badge"
            chips += f'<span class="{css}">{esc(localize_badge(badge, "zh"))}</span>'
        cites = int(item.get("cited_by") or 0)
        cite = f'<span class="cite">{cites} 次被引</span>' if cites else ""
        venue = f'<span class="venue">{esc(item["venue"])}</span>' if item["venue"] else ""
        tail = f"，{esc(item['year'])}" if item["year"] else ""
        note = ""
        if with_note:
            rate_txt = item.get("rating") or "推荐表未收录"
            ccf_txt = f"，{item['ccf']}" if item.get("ccf") else ""
            pos = item.get("position")
            role_txt = "、".join(item.get("tags") or []) or (f"第 {pos} 作者" if pos else "—")
            parts = [f"推荐指数：{rate_txt}{ccf_txt}", f"署名：{role_txt}"]
            if item.get("exclude_reason"):
                parts.append(f"未计入原因：{item['exclude_reason']}")
            note = f'<div class="group-note">{" · ".join(parts)}</div>'
        rows.append(
            f'<li><span class="num">[{idx}]</span> <span class="ptitle">{esc(item["title"])}</span>。'
            f"{venue}{tail}。"
            f'<div class="pauth">{pub_authors_html(item, me_name)}</div>'
            f'<div class="pmeta">{tags}{rate}{chips}{pub_links_html(item)}{cite}</div>{note}</li>'
        )
    return "\n".join(rows)


def build_core_html() -> str:
    cfg = TARGETS["core_zh"]
    data = content_zh()
    main, others, preprints = prepare_core_items()
    generated = datetime.now().strftime("%Y-%m-%d")

    criteria = (
        "筛选口径：① <b>2021 年及以后</b>发表（含在线发表）的期刊/会议论文；"
        "② 刊物/会议的<b>推荐指数 A+ 及以上</b>（依据课题组《AI&amp;DM&amp;NLP&amp;BioMed 刊物推荐表 2024.09》；"
        "推荐顺序 A+++ &gt; A++ &gt; A+ &gt; A &gt; A- &gt; B；CCF-A 类期刊与 CCF-A 类会议长文按表内口径计为 A+ 及以上）；"
        "③ 署名角色为 <b>第一作者 / 共同第一作者 / 通讯作者 / 共同通讯作者 / 导师第一作者·本人第二作者</b> 之一"
        "（导师指张颖教授、秦璐教授、王翰宸博士、王潇杨教授）。"
        "预印本（arXiv）、<b>会议短文（Extended Abstract）</b>、以及一作非导师的合著论文均不计入。"
    )
    legend = (
        "标签：<span class=\"tag\">一作</span>第一作者　<span class=\"tag\">通讯作者</span>"
        "<span class=\"tag\">导师一作·学生二作</span><span class=\"tag\">共同一作 / 共同通讯</span>（人工确认后标注）　"
        "│ 等级：<span class=\"badge ccf\">A+++</span><span class=\"badge ccf\">A+</span> = 推荐表推荐指数；"
        "CCF-A/B/C = CCF 推荐目录；中科院 N 区 / JCR Qn = 期刊分区。"
    )

    return f"""<!DOCTYPE html>
<!-- GENERATED by scripts/build_cv.py (core-zh) — 请勿手工编辑。
     筛选规则：data/venue_ratings.yml（刊物推荐表）+ data/publication_roles.yml（通讯作者事实）
     + content/publications/**（论文与作者顺序）。重新生成：python3 scripts/build_cv.py --only core --pdf
     生成日期 {generated} -->
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(data["name"])} — 代表性论文（入职材料）</title>
<style>{CSS}</style>
</head>
<body data-lang="zh-CN">
<div class="toolbar no-print">
  <button onclick="window.print()">打印 · 存为 PDF</button>
  <a href="{esc(cfg['pdf_href'])}">下载 PDF</a>
  <a href="{esc(cfg['cv_href'])}">{esc(LABELS["zh"]["back_cv"])}</a>
  <a href="{esc(cfg['alt_href'])}">完整论文列表</a>
</div>
<div class="sheet">
  {page_header_html(cfg, data)}

  {h2("代表性论文（A+ 及以上 · 限定署名角色）")}
  <div class="criteria">{criteria}</div>
  <div class="legend">{legend}</div>
  <ul class="pubs pubs-full">
{core_rows_html(main, AUTHOR_LINE_NAME)}
  </ul>

  {h2("其他论文（2021 年起，未计入上述筛选）")}
  <ul class="pubs pubs-full">
{core_rows_html(others, AUTHOR_LINE_NAME, start=len(main) + 1, with_note=True)}
  </ul>

  {h2("预印本（未正式发表）") if preprints else ""}
  {f'<div class="group-note">以下为 arXiv 预印本，尚未正式发表，单独列出、不计入上述统计。</div>' if preprints else ""}
  {f'<ul class="pubs pubs-full">{chr(10)}{core_rows_html(preprints, AUTHOR_LINE_NAME, start=len(main) + len(others) + 1, with_note=True)}{chr(10)}</ul>' if preprints else ""}

  <div class="foot">
    <span>生成于 {esc(generated)}</span>
    <span>共 {len(main)} 篇符合筛选口径 · 完整列表：{esc(SITE)}/cv/zh/publications/</span>
  </div>
</div>
</body>
</html>
"""


def build_html(lang: str) -> str:
    cfg = TARGETS[lang]
    labels = LABELS[lang]
    data = content_en() if lang == "en" else content_zh()
    generated = datetime.now().strftime("%d %b %Y") if lang == "en" else datetime.now().strftime("%Y-%m-%d")

    # 联系方式：小标签 + 短标识，一行流动、· 分隔（标签是给打印稿看的）
    contact = " · ".join(
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
    sections = data.get("sections") or {}
    skills_block = f'{h2(labels["skills"])}\n{skills}' if sections.get("skills", True) and skills else ""
    # page_break_before: false / 段落 key（publications、scholarships、honors…）/ true（= publications）
    pb = data["pub_cfg"].get("page_break_before")
    pb = "publications" if pb is True else ("" if not pb else str(pb))

    def brk(key: str) -> str:
        return '<div class="page-break"></div>' if pb == key else ""

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
  <a href="{esc(cfg['pubs_href'])}">{esc(labels["pubs_button"])}</a>
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

  {brk("publications")}
  {h2(labels["publications"])}
  {pubs_block(data["pub_cfg"], lang)}

  {brk("scholarships")}
  {h2(labels["scholarships"])}
  {entries_html(data["scholarships"])}

  {brk("honors")}
  {h2(labels["honors"])}
  {entries_html(data["awards"])}

  {brk("activities")}
  <div class="cols">
    <div>
      {h2(labels["activities"])}
      {entries_compact_html(data["talks"])}
      {entries_compact_html(data["service"])}
    </div>
    <div>
      {h2(labels["teaching"])}
      {entries_compact_html(data["teaching"])}
    </div>
  </div>

  {skills_block}

  <div class="foot">
    <span>{esc(labels["updated"])} {esc(generated)}</span>
    <span>{esc(labels["full_list"])}: {esc(SITE)}/cv/publications/</span>
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


def build_pdf(cfg: dict) -> int:
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
    parser = argparse.ArgumentParser(description="生成 A4 可打印简历 / 完整论文列表（en / zh）")
    parser.add_argument("--pdf", action="store_true", help="同时渲染 PDF")
    parser.add_argument("--lang", choices=("en", "zh", "both"), default="both", help="生成哪一版")
    parser.add_argument(
        "--only",
        choices=("all", "cv", "pubs", "core"),
        default="all",
        help="all=简历+论文列表+入职版；cv=只生成简历；pubs=只生成完整论文列表；core=只生成工商入职版",
    )
    args = parser.parse_args()

    if not PHOTO.exists():
        print(f"[warn] 缺少证件照 {PHOTO.relative_to(ROOT)}，页面头部将不显示照片", file=sys.stderr)

    langs = ("en", "zh") if args.lang == "both" else (args.lang,)
    keys: list[str] = []
    if args.only in ("all", "cv"):
        keys += list(langs)
    if args.only in ("all", "pubs"):
        keys += [f"pubs_{lang}" for lang in langs]
    if args.only in ("all", "core"):
        keys += ["core_zh"]

    rc = 0
    for key in keys:
        cfg = TARGETS[key]
        cfg["dir"].mkdir(parents=True, exist_ok=True)
        kind = cfg["kind"]
        if kind == "pubs":
            html = build_publications_html(cfg["lang"])
        elif kind == "core":
            html = build_core_html()
        else:
            html = build_html(key)
        cfg["html"].write_text(html, encoding="utf-8")
        print(f"[html] {cfg['html'].relative_to(ROOT)}  {cfg['html'].stat().st_size / 1024:.0f} KB")
        if args.pdf:
            rc |= build_pdf(cfg)
    return rc


if __name__ == "__main__":
    sys.exit(main())
