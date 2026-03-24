import os
import re
import time
import urllib.request
import json
from github import Github, Auth

GITHUB_TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
GITHUB_REPO  = "soomin-umd/soomin-umd.github.io"


def get_repo():
    auth = Auth.Token(GITHUB_TOKEN)
    g = Github(auth=auth)
    return g.get_repo(GITHUB_REPO)


def extract_article_link(content):
    m = re.search(r'\[Full Article\]\((https?://[^\s\)]+)\)', content)
    if m:
        return m.group(1)
    return ''


def extract_doi_from_url(url):
    if not url:
        return ''
    m = re.search(r'(10\.\d{4,}/[^\s?#]+)', url)
    if m:
        return m.group(1)
    return ''


def fetch_real_date(doi):
    if not doi:
        return ''
    try:
        url = f"https://api.crossref.org/works/{doi}"
        req = urllib.request.Request(url, headers={'User-Agent': 'LitBot/1.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            msg = data.get('message', {})

            for date_field in ['published-online', 'published-print', 'issued']:
                date_obj = msg.get(date_field, {})
                parts = date_obj.get('date-parts', [[]])[0]
                if parts and len(parts) >= 3:
                    return f"{parts[0]}-{parts[1]:02d}-{parts[2]:02d}"
                elif parts and len(parts) == 2:
                    return f"{parts[0]}-{parts[1]:02d}-01"
                elif parts and len(parts) == 1:
                    return f"{parts[0]}-01-01"
            return ''
    except Exception as e:
        print(f"  Crossref error: {e}")
        return ''


def update_date_in_content(content, new_date):
    return re.sub(
        r'^(date:\s*)(.+)$',
        r'\g<1>' + new_date,
        content,
        count=1,
        flags=re.MULTILINE,
    )


def update_published_in_content(content, new_date):
    return re.sub(
        r'(\*\*Published:\*\*\s*)\d{4}-\d{2}-\d{2}',
        r'\g<1>' + new_date,
        content,
        count=1,
    )


def main():
    if not GITHUB_TOKEN:
        print("NO TOKEN")
        return

    repo = get_repo()
    print("Connected to repo")

    contents = repo.get_contents("_posts")
    posts = [f for f in contents if f.name.endswith('.md')]
    print(f"Found {len(posts)} posts")

    post_data = []
    for p in posts:
        raw = p.decoded_content.decode('utf-8')
        link = extract_article_link(raw)
        doi = extract_doi_from_url(link)
        post_data.append({
            'file': p,
            'name': p.name,
            'content': raw,
            'link': link,
            'doi': doi,
        })

    # Phase 1: Crossref에서 실제 날짜 가져오기
    print("\n--- Fetching real dates from Crossref ---")
    for pd_item in post_data:
        doi = pd_item['doi']
        if doi:
            real_date = fetch_real_date(doi)
            if real_date:
                pd_item['real_date'] = real_date
                print(f"  {real_date} | {pd_item['name'][:50]}")
            else:
                pd_item['real_date'] = ''
                print(f"  NO DATE | {pd_item['name'][:50]}")
            time.sleep(0.3)
        else:
            pd_item['real_date'] = ''
            print(f"  NO DOI | {pd_item['name'][:50]}")

    # Phase 2: 날짜순 정렬 + 타임스탬프 부여
    has_date = [p for p in post_data if p['real_date']]
    no_date = [p for p in post_data if not p['real_date']]
    print(f"\nWith real date: {len(has_date)}, Without: {len(no_date)}")

    has_date.sort(key=lambda x: (x['real_date'], x['name']))

    date_counter = {}
    updated = 0

    for pd_item in has_date:
        pub = pd_item['real_date']

        if pub not in date_counter:
            date_counter[pub] = 0
        date_counter[pub] += 1
        count = date_counter[pub]

        hours = count // 60
        minutes = count % 60
        new_date_full = f"{pub} {hours:02d}:{minutes:02d}:00 +0000"

        new_content = update_date_in_content(pd_item['content'], new_date_full)
        new_content = update_published_in_content(new_content, pub)

        new_name = re.sub(r'^\d{4}-\d{2}-\d{2}', pub, pd_item['name'])
        new_path = f"_posts/{new_name}"
        old_path = pd_item['file'].path

        try:
            if new_path != old_path:
                repo.create_file(
                    path=new_path,
                    message=f"Fix: {pub} | {new_name[:40]}",
                    content=new_content,
                )
                repo.delete_file(
                    path=old_path,
                    message=f"Del: {pd_item['name'][:40]}",
                    sha=pd_item['file'].sha,
                )
                print(f"  OK [{updated+1}] {new_date_full} | {new_name[:50]}")
            else:
                if new_content != pd_item['content']:
                    repo.update_file(
                        path=old_path,
                        message=f"Fix: {pub} | {pd_item['name'][:40]}",
                        content=new_content,
                        sha=pd_item['file'].sha,
                    )
                    print(f"  OK [{updated+1}] {new_date_full} | {pd_item['name'][:50]}")
                else:
                    print(f"  SKIP (no change) | {pd_item['name'][:50]}")
                    continue

            updated += 1
            time.sleep(0.5)

        except Exception as e:
            print(f"  ERR: {pd_item['name'][:40]} | {e}")

    print(f"\nDone! {updated} posts updated with real published dates")


if __name__ == "__main__":
    main()
