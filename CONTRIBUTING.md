# Contributing Guide

## 브랜치 전략

**main 브랜치에 직접 push 금지**

모든 작업은 본인 브랜치에서 진행 후 PR을 통해 main에 병합합니다.

| 브랜치 | 용도 |
|--------|------|
| `main` | 배포 브랜치 — 직접 push 금지 |
| `feat/이름` | 개인 작업 브랜치 |

## 작업 흐름

```
1. 본인 브랜치로 이동
   git checkout feat/이름

2. main 최신 내용 받기
   git pull origin main

3. 작업 후 커밋
   git add 파일명
   git commit -m "feat: 작업 내용"

4. 본인 브랜치에 push
   git push origin feat/이름

5. GitHub에서 PR 생성 → main으로 병합 요청
```

## 커밋 메시지 규칙

```
feat:  새 기능 추가
fix:   버그 수정
docs:  문서 수정
style: 코드 포맷 변경 (기능 변화 없음)
refactor: 리팩토링
```

## 주의사항

- `git push origin main` 직접 실행 금지
- 작업 전 반드시 `git pull origin main` 으로 최신 상태 유지
- 충돌 발생 시 혼자 해결하지 말고 팀원과 상의
