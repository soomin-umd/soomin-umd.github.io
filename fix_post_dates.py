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


def extract_slug(filename):
    """파일명에서 날짜 제거하고 slug만 추출
    예: 2026-03-24-litnote-whose-last-dollar-est.md -> litnote-whose-last-dollar-est.md
    """
    m = re.match(r'\d{4}-\d{2}-\d{2}-(.*)', filename)
    if m:
        return m.group(1)
    return filename


def extract_date(filename):
    """파일명에서 날짜 추출"""
    m = re.match(r'(\d{4}-\d{2}-\d{2})', filename)
    if m:
        return m.group(1)
    return ''


def main():
    if not GITHUB_TOKEN:
        print("NO TOKEN")
        return

    repo = get_repo()
    print("Connected to repo")

    contents = repo.get_contents("_posts")
    posts = [f for f in contents if f.name.endswith('.md')]
    print(f"Found {len(posts)} posts total")

    # slug별로 그룹핑
    groups = {}
    for p in posts:
        slug = extract_slug(p.name)
        if slug not in groups:
            groups[slug] = []
        groups[slug].append(p)

    # 중복 찾기
    duplicates_to_delete = []
    for slug, files in groups.items():
        if len(files) > 1:
            # 날짜 기준 정렬 (가장 이른 날짜 = 실제 게재일)
            files.sort(key=lambda f: extract_date(f.name))
            keep = files[0]
            delete = files[1:]
            print(f"\n  KEEP: {keep.name}")
            for d in delete:
                print(f"  DELETE: {d.name}")
                duplicates_to_delete.append(d)

    print(f"\n{'='*60}")
    print(f"Keeping: {len(groups)} unique posts")
    print(f"Deleting: {len(duplicates_to_delete)} duplicates")
    print(f"{'='*60}\n")

    # 삭제 실행
    deleted = 0
    for f in duplicates_to_delete:
        try:
            repo.delete_file(
                path=f.path,
                message=f"Cleanup duplicate: {f.name[:50]}",
                sha=f.sha,
            )
            deleted += 1
            print(f"  Deleted [{deleted}]: {f.name[:60]}")
            time.sleep(0.3)
        except Exception as e:
            print(f"  Error deleting {f.name[:40]}: {e}")

    print(f"\nDone! Deleted {deleted} duplicate files")
    print(f"Remaining posts: {len(posts) - deleted}")


if __name__ == "__main__":
    main()
