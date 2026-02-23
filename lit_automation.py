import os
import feedparser
import anthropic
from pyzotero import zotero
from github import Github
import datetime
import re
import time

# ── API Keys (GitHub Secrets) ────────────────────────────────────────────────
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY")
ZOTERO_API_KEY = os.environ.get("ZOTERO_API_KEY")
ZOTERO_USER_ID = "19141751"
GITHUB_TOKEN   = os.environ.get("GH_TOKEN")
GITHUB_REPO    = "soomin-umd/soomin-umd.github.io"

# ── RSS Feeds ────────────────────────────────────────────────────────────────
RSS_FEEDS = {
    "Research in Higher Education":
        "https://link.springer.com/search.rss?facet-content-type=Article&facet-journal-id=11162",
    "Journal of Higher Education":
        "https://www.tandfonline.com/feed/rss/uhej20",
    "Educational Evaluation and Policy Analysis":
        "https://journals.sagepub.com/action/showFeed?jc=epaa&type=etoc&feed=rss",
    "Journal of Policy Analysis and Management":
        "https://onlinelibrary.wiley.com/feed/15206688/most-recent",
}

# ── Keywords ─────────────────────────────────────────────────────────────────
QUANT_KEYWORDS = [
    "difference-in-differences", "difference in differences",
    r"\bdid\b",                                  # ← 단어 경계로 오탐 방지
    "d-i-d", "regression discontinuity", "rdd", "rd design",
    "instrumental variable", "two-stage least squares", "2sls",
    "propensity score", "psm", "matching estimat",
    "panel data", "fixed effects", "random effects",
    "synthetic control", "event study",
    "quasi-experimental", "natural experiment",
    "causal inference", "causal identification", "causal effect",
    "multilevel model", "hierarchical linear model", "ols regression",
    "interrupted time series", "its analysis", "segmented regression",
    "triple difference", "difference-in-difference-in-differences",
    "staggered adoption", "callaway", "sant'anna",
    "heterogeneous treatment",
]

K12_KEYWORDS = [
    "k-12", "k12", "elementary school", "middle school",
    "primary school", "secondary school", "kindergarten",
    "grade school", "school district", "preschool", "pre-k",
    "early childhood", "p-12", "p12",
    # "literacy" 제거 → higher ed에서도 자주 쓰임 (financial literacy 등)
]

TITLE_KEYWORDS = [
    "financial aid", "tuition", "selectivity", "equity",
    "access", "enrollment", "college completion",
    "first-generation", "intergenerational", "mobility",
    "scholarship", "affordability", "student loan",
    "transfer", "retention", "attainment",
]


# ── Filter ───────────────────────────────────────────────────────────────────
def passes_filter(title: str, abstract: str) -> tuple[bool, str]:
    text       = (title + " " + abstract).lower()
    title_text = title.lower()

    # K-12 reject
    for kw in K12_KEYWORDS:
        if kw in text:
            return False, f"K-12 detected: '{kw}'"

    # Quant method match (정규식 지원)
    quant_match = next(
        (kw for kw in QUANT_KEYWORDS if re.search(kw, text)), None
    )

    # Topic keyword in title
    title_match = next(
        (kw for kw in TITLE_KEYWORDS if kw in title_text), None
    )

    if not quant_match and not title_match:
        return False, "No quant/topic keyword"

    matched = quant_match or title_match
    return True, f"Match: '{matched}'"


# ── Zotero save ───────────────────────────────────────────────────────────────
def save_to_zotero(paper: dict):
    zot  = zotero.Zotero(ZOTERO_USER_ID, 'user', ZOTERO_API_KEY)
    item = zot.item_template('journalArticle')
    item['title']            = paper['title']
    item['url']              = paper['link']
    item['publicationTitle'] = paper['journal']
    item['date']             = paper['date']
    item['abstractNote']     = paper['abstract']
    item['tags']             = [
        {'tag': 'auto-imported'},
        {'tag': 'quant-methods'},
        {'tag': 'higher-ed'},
    ]
    zot.create_items([item])
    print("  📚 Saved to Zotero")


# ── Claude summary ────────────────────────────────────────────────────────────
def generate_summary(paper: dict) -> str:
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    prompt = f"""Analyze the following higher education paper.
I am a PhD student researching intergenerational educational mobility,
first-generation college students (FGCS), and state financial aid policy.

Title: {paper['title']}
Journal: {paper['journal']}
Date: {paper['date']}
Abstract: {paper['abstract']}

Please write in English using the format below:

## 📌 Core Research Question

## 🔬 Methodology
(Specify identification strategy in detail: DiD, RD, IV, PSM, etc.)

## 📊 Key Findings
(Include specific numbers/effect sizes if available)

## 💡 Relevance to My Research
(Connect to intergenerational mobility, FGCS, and/or state financial aid policy)

## ⭐ Key Quote Worth Citing (verbatim from abstract)
"""
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


# ── GitHub post ───────────────────────────────────────────────────────────────
def sanitize_title(title: str) -> str:
    """YAML front matter에서 따옴표 충돌 방지"""
    return title.replace('"', "'").replace(':', ' -')


def post_to_github(paper: dict, summary: str, source_label: str = "RSS"):
    g     = Github(GITHUB_TOKEN)
    repo  = g.get_repo(GITHUB_REPO)
    today = datetime.date.today()
    slug  = re.sub(r'[^a-z0-9\-]', '',
                   paper['title'][:40].lower().replace(' ', '-'))
    filename = f"_posts/{today}-litnote-{slug}.md"

    safe_title = sanitize_title(paper['title'])

    content = f"""---
title: "[LitNote] {safe_title}"
date: {today}
categories: [Literature Notes]
tags: [quant-methods, higher-ed, auto-summary]
source: {source_label}
---

> **Journal:** {paper['journal']}
> **Published:** {paper['date']}
> **Source:** [Full Article]({paper['link']})

---

{summary}

---
*🤖 Auto-generated using Claude API | Source: {source_label}*
"""
    try:
        repo.create_file(
            path=filename,
            message=f"Auto LitNote: {paper['title'][:50]}",
            content=content,
        )
        print(f"  📝 Posted to blog: {filename}")
    except Exception as e:
        if "already exists" in str(e):
            print("  ⏭️  Already posted, skipping")
        else:
            print(f"  ⚠️ GitHub error: {e}")


# ── Pipeline 1: RSS Feed (22일 주기) ──────────────────────────────────────────
def run_rss_pipeline(days_back: int = 22):
    print(f"\n{'='*60}")
    print("📡 [Pipeline 1] RSS Feed Scan")
    print(f"   Scanning last {days_back} days")
    print(f"{'='*60}")

    cutoff = datetime.datetime.now() - datetime.timedelta(days=days_back)
    passed = []

    for journal, url in RSS_FEEDS.items():
        print(f"\n  Fetching: {journal}")
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"  ⚠️ RSS error: {e}")
            continue

        for entry in feed.entries:
            pub_date = (
                datetime.datetime(*entry.published_parsed[:6])
                if hasattr(entry, 'published_parsed') and entry.published_parsed
                else datetime.datetime.now()
            )
            if pub_date < cutoff:
                continue

            title    = entry.get('title', '')
            abstract = entry.get('summary', '')
            link     = entry.get('link', '')

            ok, reason = passes_filter(title, abstract)
            if ok:
                passed.append({
                    'title': title, 'abstract': abstract,
                    'link': link, 'journal': journal,
                    'date': pub_date.strftime('%Y-%m-%d'),
                })
                print(f"  ✅ PASS | {reason} | {title[:60]}...")
            else:
                print(f"  ⏭️  SKIP ({reason})")

    print(f"\n  → {len(passed)} papers passed filters")

    for i, paper in enumerate(passed, 1):
        print(f"\n[{i}/{len(passed)}] {paper['title'][:65]}...")
        try:
            save_to_zotero(paper)
        except Exception as e:
            print(f"  ⚠️ Zotero error: {e}")

        print("  🤖 Generating summary...")
        try:
            summary = generate_summary(paper)
        except Exception as e:
            print(f"  ⚠️ Claude error: {e}")
            continue

        post_to_github(paper, summary, source_label="RSS")
        time.sleep(2)

    print(f"\n✅ RSS Pipeline done: {len(passed)} papers processed.")
    return len(passed)


# ── Pipeline 2: Zotero Queue (수동 추가분) ────────────────────────────────────
def run_zotero_pipeline(days_back: int = 22):
    print(f"\n{'='*60}")
    print("📚 [Pipeline 2] Zotero Queue Scan")
    print(f"   Checking items added in last {days_back} days")
    print(f"{'='*60}")

    zot     = zotero.Zotero(ZOTERO_USER_ID, 'user', ZOTERO_API_KEY)
    items   = zot.items(sort='dateAdded', direction='desc', limit=50)
    cutoff  = datetime.datetime.now() - datetime.timedelta(days=days_back)
    processed = 0

    for item in items:
        data = item.get('data', {})

        # 기간 체크
        date_added = data.get('dateAdded', '')
        if date_added:
            added_dt = datetime.datetime.strptime(date_added[:19], '%Y-%m-%dT%H:%M:%S')
            if added_dt < cutoff:
                continue

        # auto-imported 태그 = RSS에서 이미 처리된 항목 → 스킵
        tags = [t['tag'] for t in data.get('tags', [])]
        if 'auto-imported' in tags:
            continue

        # blog-posted 태그 = 이미 블로그에 올린 항목 → 중복 방지
        if 'blog-posted' in tags:
            continue

        title    = data.get('title', '')
        abstract = data.get('abstractNote', '')
        link     = data.get('url', '')
        journal  = data.get('publicationTitle', 'Unknown Journal')
        date     = data.get('date', str(datetime.date.today()))[:10]

        ok, reason = passes_filter(title, abstract)
        if not ok:
            print(f"  ⏭️  SKIP ({reason}) | {title[:50]}...")
            continue

        print(f"\n  ✅ MATCH | {reason} | {title[:60]}...")

        paper = {
            'title': title, 'abstract': abstract,
            'link': link, 'journal': journal, 'date': date,
        }

        print("  🤖 Generating summary...")
        try:
            summary = generate_summary(paper)
        except Exception as e:
            print(f"  ⚠️ Claude error: {e}")
            continue

        post_to_github(paper, summary, source_label="Zotero")

        # 처리 완료 표시 → 다음 실행 때 중복 방지
        try:
            zot.update_item({
                **item,
                'data': {
                    **data,
                    'tags': data.get('tags', []) + [{'tag': 'blog-posted'}],
                }
            })
            print("  🏷️  Tagged 'blog-posted' in Zotero")
        except Exception as e:
            print(f"  ⚠️ Tag update error: {e}")

        processed += 1
        time.sleep(2)

    print(f"\n✅ Zotero Pipeline done: {processed} papers processed.")
    return processed


# ── Main: 두 파이프라인 통합 실행 ─────────────────────────────────────────────
def run_all(days_back: int = 22):
    print("\n🚀 Starting Literature Automation Pipeline")
    print(f"   Scan window: {days_back} days\n")

    rss_count    = run_rss_pipeline(days_back=days_back)
    zotero_count = run_zotero_pipeline(days_back=days_back)

    print(f"\n{'='*60}")
    print("🎉 All Done!")
    print(f"   RSS papers posted   : {rss_count}")
    print(f"   Zotero papers posted: {zotero_count}")
    print(f"   Blog: https://soomin-umd.github.io")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    run_all(days_back=22)
