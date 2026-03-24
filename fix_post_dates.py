"""
fix_post_dates.py (v2)
──────────────────────
기존 블로그 포스트들의 front matter date를
논문의 실제 Published 날짜(저널 게재일) 기준으로 업데이트.

→ 최신 논문이 page 1에 오도록 정렬됨.

사용법:
  레포에 업로드 후 Actions → "Fix Post Dates" → Run workflow
"""

import os
import re
import time
from github import Github, Auth

# ── 설정 ──────────────────────────────────────────────────────────────────────
GITHUB_TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
GITHUB_REPO  = "soomin-umd/soomin-umd.github.io"


def get_repo():
    auth = Auth.Token(GITHUB_TOKEN)
    g = Github(auth=auth)
    return g.get_repo(GITHUB_REPO)


def extract_published_date(content: str) -> str:
    """포스트 본문에서 논문의 Published 날짜 추출"""
    m = re.search(r'\*\*Published:\*\*\s*(\d{4}-\d{2}-\d{2})', content)
    if m:
        return m.group(1)
    return ""


def update_date_in_content(content: str, new_date: str) -> str:
    """front matter의 date 값을 새 타임스탬프로 교체"""
    return re.sub(
        r'^(date:\s*)(.+)$',
        rf'\g<1>{new_date}',
        content,
        count=1,
        flags=re.MULTILINE,
    )


def update_filename_date(old_name: str, new_date_str: str) -> str:
    """파일명의 날짜 부분도 Published 날짜로 변경
    예: 2026-02-24-litnote-xxx.md → 2026-03-24-litnote-xxx.md
    """
    return re.sub(r'^\d{4}-\d{2}-\d{2}', new_date_str, old_name)


def main():
    if not GITHUB_TOKEN:
        print("❌ GH_TOKEN 환경변수를 설정해주세요.")
        return

    repo = get_repo()
    print(f"📂 레포 연결: {GITHUB_REPO}")

    # ── _posts/ 폴더의 모든 파일 가져오기 ──
    contents = repo.get_contents("_posts")
    posts = [f for f in contents if f.name.endswith('.md')]
    print(f"📄 총 {len(posts)}개 포스트 발견\n")

    # ── 각 포스트의 Published 날짜 수집 ──
    post_data = []
    for p in posts:
        raw = p.decoded_content.decode('utf-8')
        pub_date = extract_published_date(raw)

        post_data.append({
            'file': p,
            'name': p.name,
            'content': raw,
            'published_date': pub_date or '2026-01-01',
