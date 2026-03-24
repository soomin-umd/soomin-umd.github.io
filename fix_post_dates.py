"""
fix_post_dates.py
─────────────────
기존 블로그 포스트들의 date를 고유한 타임스탬프로 업데이트하여
최신 순 정렬이 되도록 수정하는 일회성 스크립트.

사용법:
  1) GitHub Actions로 실행 (권장)
  2) 로컬에서 실행: GH_TOKEN=xxx python fix_post_dates.py

정렬 로직:
  - 포스트 내 논문의 Published 날짜를 1차 정렬 기준으로 사용
  - 같은 날짜인 경우, 파일명(제목) 알파벳 순으로 2차 정렬
  - 각 포스트에 1분 간격의 고유 타임스탬프 부여
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
    # > **Published:** 2026-02-24  패턴 매칭
    m = re.search(r'\*\*Published:\*\*\s*(\d{4}-\d{2}-\d{2})', content)
    if m:
        return m.group(1)
    return ""


def extract_front_matter_date(content: str) -> str:
    """front matter에서 현재 date 값 추출"""
    m = re.search(r'^date:\s*(.+)$', content, re.MULTILINE)
    if m:
        return m.group(1).strip()
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

    # ── 각 포스트의 Published 날짜와 파일명 수집 ──
    post_data = []
    for p in posts:
        raw = p.decoded_content.decode('utf-8')
        pub_date = extract_published_date(raw)
        current_date = extract_front_matter_date(raw)

        post_data.append({
            'file': p,
            'name': p.name,
            'content': raw,
            'published_date': pub_date or '9999-99-99',  # 날짜 없으면 맨 뒤로
            'current_date': current_date,
        })

    # ── 정렬: Published 날짜 오름차순 → 파일명 알파벳 순 ──
    #    (오래된 논문 → 최근 논문 순서로 시간 부여, 최근이 가장 늦은 시각)
    post_data.sort(key=lambda x: (x['published_date'], x['name']))

    # ── 타임스탬프 부여 ──
    #    가장 오래된 논문 = 00:01, 그 다음 = 00:02, ...
    #    → Jekyll은 나중 시각이 먼저 표시되므로 최신 논문이 page 1에 옴
    updated = 0
    skipped = 0

    for i, pd in enumerate(post_data):
        # 파일명에서 날짜 추출 (2026-02-24-litnote-xxx.md → 2026-02-24)
        date_match = re.match(r'(\d{4}-\d{2}-\d{2})', pd['name'])
        if not date_match:
            print(f"  ⏭️  날짜 없는 파일, 스킵: {pd['name']}")
            skipped += 1
            continue

        base_date = date_match.group(1)

        # 이미 시간이 포함된 date면 스킵
        if ':' in pd['current_date']:
            print(f"  ⏭️  이미 타임스탬프 있음, 스킵: {pd['name']}")
            skipped += 1
            continue

        # 1분 간격 타임스탬프 (00:01 ~ )
        hours = (i + 1) // 60
        minutes = (i + 1) % 60
        new_date = f"{base_date} {hours:02d}:{minutes:02d}:00 -0500"

        new_content = update_date_in_content(pd['content'], new_date)

        # GitHub에 업데이트
        try:
            repo.update_file(
                path=pd['file'].path,
                message=f"Fix date: add timestamp to {pd['name'][:40]}",
                content=new_content,
                sha=pd['file'].sha,
            )
            print(f"  ✅ [{i+1}/{len(post_data)}] {new_date} | {pd['name'][:55]}")
            updated += 1
            time.sleep(0.5)  # API rate limit 방지
        except Exception as e:
            print(f"  ⚠️  업데이트 실패: {pd['name'][:40]} | {e}")

    print(f"\n{'='*60}")
    print(f"🎉 완료!")
    print(f"   업데이트: {updated}개")
    print(f"   스킵:     {skipped}개")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
