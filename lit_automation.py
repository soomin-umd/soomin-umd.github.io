import os
import feedparser
import anthropic
from pyzotero import zotero
from github import Github
import datetime
import re
import time

# Keys from GitHub Secrets (automatically injected)
CLAUDE_API_KEY  = os.environ.get("CLAUDE_API_KEY")
ZOTERO_API_KEY  = os.environ.get("ZOTERO_API_KEY")
ZOTERO_USER_ID  = "19141751"
GITHUB_TOKEN    = os.environ.get("GH_TOKEN")
GITHUB_REPO     = "soomin-umd/soomin-umd.github.io"

RSS_FEEDS = {
    "Research in Higher Education":
        "https://link.springer.com/search.rss?facet-content-type=Article&facet-journal-id=11162",
    "Journal of Higher Education":
        "https://www.tandfonline.com/feed/rss/uhej20",
    "Education Finance and Policy":
        "https://direct.mit.edu/rss/journals/edfp",
    "Educational Evaluation and Policy Analysis":
        "https://journals.sagepub.com/action/showFeed?jc=epaa&type=etoc&feed=rss",
    "Journal of Policy Analysis and Management":
        "https://onlinelibrary.wiley.com/feed/15206688/most-recent",
}

QUANT_KEYWORDS = [
    "difference-in-differences", "difference in differences", "did ", "d-i-d",
    "regression discontinuity", "rdd", "rd design",
    "instrumental variable", "two-stage least squares", "2sls",
    "propensity score", "psm", "matching estimat",
    "panel data", "fixed effects", "random effects",
    "synthetic control", "event study",
    "quasi-experimental", "natural experiment",
    "causal inference", "causal identification", "causal effect",
    "multilevel model", "hierarchical linear model", "ols regression",
]

K12_KEYWORDS = [
    "k-12", "k12", "elementary school", "middle school",
    "primary school", "secondary school", "kindergarten",
    "grade school", "school district", "preschool", "pre-k",
    "early childhood", "p-12", "p12", "literacy",
]

def passes_filter(title, abstract):
    text = (title + " " + abstract).lower()
    for kw in K12_KEYWORDS:
        if kw in text:
            return False, f"K-12 detected: '{kw}'"
    quant_match = [kw for kw in QUANT_KEYWORDS if kw in text]
    if not quant_match:
        return False, "No quant method keyword"
    return True, f"Method: '{quant_match[0]}'"

def fetch_papers(days_back=21):
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days_back)
    passed = []
    for journal, url in RSS_FEEDS.items():
        print(f"\n📡 Fetching: {journal}")
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"  ⚠️ RSS error: {e}")
            continue
        for entry in feed.entries:
            pub_date = datetime.datetime(*entry.published_parsed[:6]) \
                       if hasattr(entry, 'published_parsed') and entry.published_parsed \
                       else datetime.datetime.now()
            if pub_date < cutoff:
                continue
            title    = entry.get('title', '')
            abstract = entry.get('summary', '')
            link     = entry.get('link', '')
            ok, reason = passes_filter(title, abstract)
            if ok:
                passed.append({'title': title, 'abstract': abstract,
                                'link': link, 'journal': journal,
                                'date': pub_date.strftime('%Y-%m-%d')})
                print(f"  ✅ PASS | {reason} | {title[:60]}...")
            else:
                print(f"  ⏭️  SKIP ({reason})")
    print(f"\n✅ {len(passed)} papers passed all filters")
    return passed

def save_to_zotero(paper):
    zot  = zotero.Zotero(ZOTERO_USER_ID, 'user', ZOTERO_API_KEY)
    item = zot.item_template('journalArticle')
    item['title']            = paper['title']
    item['url']              = paper['link']
    item['publicationTitle'] = paper['journal']
    item['date']             = paper['date']
    item['abstractNote']     = paper['abstract']
    item['tags']             = [{'tag': 'auto-imported'}, {'tag': 'quant-methods'}, {'tag': 'higher-ed'}]
    zot.create_items([item])
    print(f"  📚 Saved to Zotero")

def generate_summary(paper):
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
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text

def post_to_github(paper, summary):
    g    = Github(GITHUB_TOKEN)
    repo = g.get_repo(GITHUB_REPO)
    today = datetime.date.today()
    slug  = re.sub(r'[^a-z0-9\-]', '',
                   paper['title'][:40].lower().replace(' ', '-'))
    filename = f"_posts/{today}-litnote-{slug}.md"
    content = f"""---
title: "[LitNote] {paper['title']}"
date: {today}
categories: [Literature Notes]
tags: [quant-methods, higher-ed, auto-summary]
---

> **Journal:** {paper['journal']}
> **Published:** {paper['date']}
> **Source:** [Full Article]({paper['link']})

---

{summary}

---
*🤖 Auto-generated using Claude API*
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
            print(f"  ⏭️  Already posted, skipping")
        else:
            print(f"  ⚠️ GitHub error: {e}")

def run_pipeline(days_back=21):
    print("🚀 Starting Literature Automation Pipeline")
    print(f"   Scanning last {days_back} days\n")
    papers = fetch_papers(days_back=days_back)
    if not papers:
        print("\nNo new papers found. Done.")
        return
    print(f"\nProcessing {len(papers)} papers...\n")
    for i, paper in enumerate(papers, 1):
        print(f"[{i}/{len(papers)}] {paper['title'][:65]}...")
        try:
            save_to_zotero(paper)
        except Exception as e:
            print(f"  ⚠️ Zotero error: {e}")
        print("  🤖 Generating Claude summary...")
        try:
            summary = generate_summary(paper)
        except Exception as e:
            print(f"  ⚠️ Claude error: {e}")
            continue
        try:
            post_to_github(paper, summary)
        except Exception as e:
            print(f"  ⚠️ GitHub error: {e}")
        time.sleep(2)
    print(f"\n✅ Done! {len(papers)} papers processed.")
    print(f"   Blog: https://soomin-umd.github.io")

run_pipeline(days_back=21)
