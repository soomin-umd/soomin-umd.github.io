import os
import feedparser
import anthropic
from pyzotero import zotero
from github import Github, Auth
import datetime
import re
import time

# ── API Keys (GitHub Secrets) ────────────────────────────────────────────────
CLAUDE_API_KEY  = os.environ.get("CLAUDE_API_KEY")
ZOTERO_API_KEY  = os.environ.get("ZOTERO_API_KEY")
ZOTERO_USER_ID  = "19141751"
GITHUB_TOKEN    = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
GITHUB_REPO     = "soomin-umd/soomin-umd.github.io"

# ── RSS Feeds ────────────────────────────────────────────────────────────────
# results=100 → Springer 기본 25개 한계 우회, 최근 100개까지 수집
RSS_FEEDS = {
    "Research in Higher Education":
        "https://link.springer.com/search.rss?facet-content-type=Article&facet-journal-id=11162&results=100",
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
    r"\bdid\b",                   # ← 단어 경계로 오탐 방지
    "d-i-d", "regression discontinuity", "rdd", "rd design",
    "instrumental variable", "two-stage least squares", "2sls",
    "propensity score", "psm", "matching estimat",
    "panel data", "fixed effects", "random effects",
    "synthetic control", "event study",
    "quasi-experimental", "natural experiment",
    "causal inference", "causal identification",
    r"causal effect",             # "causal effects" 복수도 매칭
    "multilevel model", "hierarchical linear model", "ols regression",
    "logistic regression", "logit model", "probit model",
    "interrupted time series", "its analysis", "segmented regression",
    "triple difference", "difference-in-difference-in-differences",
    "staggered adoption", "callaway", "sant'anna",
    "heterogeneous treatment",
    "regression model", "multivariate regression",
    "longitudinal", "cross-sectional analysis",
]

K12_KEYWORDS = [
    "k-12", "k12", "elementary school", "middle school",
    "primary school", "secondary school", "kindergarten",
    "grade school", "school district", "preschool", "pre-k",
    "early childhood", "p-12", "p12",
]

TITLE_KEYWORDS = [
    "financial aid", "tuition", "selectivity", "equity",
    "access", "enrollment", "college completion",
    "first-generation", "first generation",
    "intergenerational", "mobility",
    "scholarship", "affordability", "student loan",
    "transfer", "retention", "attainment",
    "community college", "four-year", "postsecondary",
    "lower-income", "low-income", "pell",
    "underrepresented", "minority", "racial",
]


def fetch_abstract_from_doi(doi: str) -> str:
    """DOI로 Crossref API에서 abstract 가져오기 (Zotero에 abstract 없을 때 fallback)"""
    if not doi:
        return ''
    try:
        import urllib.request, json
        url = f"https://api.crossref.org/works/{doi}"
        req = urllib.request.Request(url, headers={'User-Agent': 'LitBot/1.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            abstract = data.get('message', {}).get('abstract', '')
            # <jats:p> 태그 제거
            abstract = re.sub(r'<[^>]+>', '', abstract).strip()
            return abstract
    except Exception as e:
        print(f"  ⚠️ Crossref fetch failed: {e}")
        return ''


# ── Filter ───────────────────────────────────────────────────────────────────
def passes_filter(title: str, abstract: str, debug: bool = False) -> tuple[bool, str]:
    text = (title + " " + abstract).lower()
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

    if debug:
        print(f"    [DEBUG] quant_match={quant_match} | title_match={title_match}")
        print(f"    [DEBUG] title='{title_text[:80]}'")
        print(f"    [DEBUG] abstract_len={len(abstract)}")

    if not quant_match and not title_match:
        return False, "No quant/topic keyword"

    matched = quant_match or title_match
    return True, f"Match: '{matched}'"


# ── Zotero save ───────────────────────────────────────────────────────────────
def is_duplicate_in_zotero(zot, title: str) -> bool:
    try:
        results = zot.items(q=title[:50])
        return len(results) > 0
    except:
        return False


def save_to_zotero(paper: dict):
    zot = zotero.Zotero(ZOTERO_USER_ID, 'user', ZOTERO_API_KEY)

    if is_duplicate_in_zotero(zot, paper['title']):
        print("  ⏭️  Already in Zotero, skipping")
        return

    item = zot.item_template('journalArticle')
    item['title']             = paper['title']
    item['url']               = paper['link']
    item['publicationTitle']  = paper['journal']
    item['date']              = paper['date']
    item['abstractNote']      = paper['abstract']
    item['tags'] = [
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
        model="claude-sonnet-4-20250514",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


# ── GitHub helpers ────────────────────────────────────────────────────────────
def _get_github_repo():
    """PyGithub repo 객체 반환 (deprecated 경고 제거)"""
    auth = Auth.Token(GITHUB_TOKEN)
    g = Github(auth=auth)
    return g.get_repo(GITHUB_REPO)


def _make_filename(paper: dict) -> str:
    """논문 제목 → _posts/ 파일명 생성"""
    today = datetime.date.today()
    slug = re.sub(r'[^a-z0-9\-]', '',
                  paper['title'][:40].lower().replace(' ', '-'))
    return f"_posts/{today}-litnote-{slug}.md"


def post_exists_on_github(repo, filename: str) -> bool:
    """GitHub repo에 해당 파일이 이미 있는지 확인 (Claude 호출 전에 체크)"""
    try:
        repo.get_contents(filename)
        return True
    except Exception:
        return False


def sanitize_title(title: str) -> str:
    """YAML front matter에서 따옴표 충돌 방지"""
    return title.replace('"', "'").replace(':', ' -')


def post_to_github(repo, paper: dict, summary: str, source_label: str = "RSS"):
    filename = _make_filename(paper)
    safe_title = sanitize_title(paper['title'])

    content = f"""---
title: "[LitNote] {safe_title}"
date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} -0500
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
        err_msg = str(e).lower()
        if "already exists" in err_msg or "sha" in err_msg:
            print(f"  ⏭️  Already posted, skipping: {filename}")
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

    # ── GitHub repo 객체를 한 번만 생성 ──
    repo = _get_github_repo()
    posted_count = 0

    for i, paper in enumerate(passed, 1):
        print(f"\n[{i}/{len(passed)}] {paper['title'][:65]}...")

        # ── (1) Zotero 저장 ──
        try:
            save_to_zotero(paper)
        except Exception as e:
            print(f"  ⚠️ Zotero error: {e}")

        # ── (2) 블로그 중복 체크 (Claude 호출 전!) ──
        filename = _make_filename(paper)
        if post_exists_on_github(repo, filename):
            print(f"  ⏭️  Already on blog, skipping Claude call: {filename}")
            continue

        # ── (3) Claude 요약 생성 ──
        print("  🤖 Generating summary...")
        try:
            summary = generate_summary(paper)
        except Exception as e:
            print(f"  ⚠️ Claude error: {e}")
            continue

        # ── (4) GitHub 포스트 ──
        post_to_github(repo, paper, summary, source_label="RSS")
        posted_count += 1
        time.sleep(2)

    print(f"\n✅ RSS Pipeline done: {posted_count} new posts out of {len(passed)} papers.")
    return posted_count


# ── Pipeline 2: Zotero Queue (수동 추가분) ────────────────────────────────────
def run_zotero_pipeline(days_back: int = 22, debug: bool = False):
    print(f"\n{'='*60}")
    print("📚 [Pipeline 2] Zotero Queue Scan")
    print(f"   Checking items added in last {days_back} days")
    if debug:
        print("   🐛 DEBUG MODE ON")
    print(f"{'='*60}")

    zot   = zotero.Zotero(ZOTERO_USER_ID, 'user', ZOTERO_API_KEY)
    items = zot.items(sort='dateAdded', direction='desc', limit=50)

    cutoff = datetime.datetime.now() - datetime.timedelta(days=days_back)

    # ── GitHub repo 객체를 한 번만 생성 ──
    repo = _get_github_repo()
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
            if debug:
                print(f"  [DEBUG] SKIP (auto-imported) | {data.get('title','')[:50]}")
            continue

        # blog-posted 태그 = 이미 블로그에 올린 항목 → 중복 방지
        if 'blog-posted' in tags:
            if debug:
                print(f"  [DEBUG] SKIP (blog-posted) | {data.get('title','')[:50]}")
            continue

        title    = data.get('title', '')
        abstract = data.get('abstractNote', '')
        link     = data.get('url', '')
        journal  = data.get('publicationTitle', 'Unknown Journal')
        date     = data.get('date', str(datetime.date.today()))[:10]
        doi      = data.get('DOI', '')

        # abstract 없으면 DOI로 Crossref에서 자동 보완
        if not abstract.strip() and doi:
            print(f"  🔍 Abstract missing, fetching from Crossref (DOI: {doi})...")
            abstract = fetch_abstract_from_doi(doi)
            if abstract:
                print(f"  ✅ Abstract fetched ({len(abstract)} chars)")

        ok, reason = passes_filter(title, abstract, debug=debug)
        if not ok:
            print(f"  ⏭️  SKIP ({reason}) | {title[:50]}...")
            continue

        print(f"\n  ✅ MATCH | {reason} | {title[:60]}...")

        paper = {
            'title': title, 'abstract': abstract,
            'link': link, 'journal': journal, 'date': date,
        }

        # ── 블로그 중복 체크 (Claude 호출 전!) ──
        filename = _make_filename(paper)
        if post_exists_on_github(repo, filename):
            print(f"  ⏭️  Already on blog, skipping Claude call: {filename}")
            continue

        print("  🤖 Generating summary...")
        try:
            summary = generate_summary(paper)
        except Exception as e:
            print(f"  ⚠️ Claude error: {e}")
            continue

        post_to_github(repo, paper, summary, source_label="Zotero")

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
