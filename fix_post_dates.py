import os
import re
import time
from github import Github, Auth

GITHUB_TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
GITHUB_REPO  = "soomin-umd/soomin-umd.github.io"


def get_repo():
    auth = Auth.Token(GITHUB_TOKEN)
    g = Github(auth=auth)
    return g.get_repo(GITHUB_REPO)


def extract_published_date(content):
    m = re.search(r'\*\*Published:\*\*\s*(\d{4}-\d{2}-\d{2})', content)
    if m:
        return m.group(1)
    return ""


def update_date_in_content(content, new_date):
    return re.sub(
        r'^(date:\s*)(.+)$',
        r'\g<1>' + new_date,
        content,
        count=1,
        flags=re.MULTILINE,
    )


def update_filename_date(old_name, new_date_str):
    return re.sub(r'^\d{4}-\d{2}-\d{2}', new_date_str, old_name)


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
        pub_date = extract_published_date(raw)
        fallback = '2026-01-01'
        post_data.append({
            'file': p,
            'name': p.name,
            'content': raw,
            'published_date': pub_date if pub_date else fallback,
        })

    post_data.sort(key=lambda x: (x['published_date'], x['name']))

    date_counter = {}
    updated = 0

    for pd_item in post_data:
        pub = pd_item['published_date']

        if pub not in date_counter:
            date_counter[pub] = 0
        date_counter[pub] += 1
        count = date_counter[pub]

        hours = count // 60
        minutes = count % 60
        new_date = f"{pub} {hours:02d}:{minutes:02d}:00 +0000"

        new_content = update_date_in_content(pd_item['content'], new_date)

        new_name = update_filename_date(pd_item['name'], pub)
        new_path = f"_posts/{new_name}"
        old_path = pd_item['file'].path

        try:
            if new_path != old_path:
                repo.create_file(
                    path=new_path,
                    message=f"Fix date: {pub} | {new_name[:40]}",
                    content=new_content,
                )
                repo.delete_file(
                    path=old_path,
                    message=f"Remove old: {pd_item['name'][:40]}",
                    sha=pd_item['file'].sha,
                )
                print(f"OK [{updated+1}] {new_date} | {new_name[:55]}")
            else:
                repo.update_file(
                    path=old_path,
                    message=f"Fix date: {pub} | {pd_item['name'][:40]}",
                    content=new_content,
                    sha=pd_item['file'].sha,
                )
                print(f"OK [{updated+1}] {new_date} | {pd_item['name'][:55]}")

            updated += 1
            time.sleep(0.5)

        except Exception as e:
            print(f"Error: {pd_item['name'][:40]} | {e}")

    print(f"Done! {updated} posts updated")


if __name__ == "__main__":
    main()
