# CHANGELOG

## [2026-08-16] — 구별 담당부서 자동 연결 · 교통 RAG 데이터 추가

### 추가
- **구별 담당부서 자동 연결** (`static/app.js`): 민원 유형(불법주정차)에 따라 AI가 지역(구·읍·면)을 물어보고 해당 담당부서 직통번호로 자동 연결
  - `COMPLAINT_INFO_NEEDS`: 민원 유형별 필요 정보 질문 매핑
  - `DISTRICT_DEPT_MAP`: 구·읍 키워드 → 담당부서 + 전화번호 매핑 (만세구·효행구·병점구·동탄구·향남·남양·동탄·병점·발안)
  - `handleDistrictCollection()`: 민원인 발화에서 지역 키워드 추출 후 연결 처리
  - `completeConnection()`: 담당부서 연결 애니메이션·메시지 공통 함수 분리
- **AI 전환 후 지역별 절차 안내** (`static/app.js`): AI 상담원 전환 후에도 수집된 지역 정보를 활용해 해당 구 기준 이의신청 절차(서류·기한·전화번호) 음성 안내
  - `DEMO_AI_COMPLAINT_RESPONSES`: 구별 하드코딩 AI 응답 (데모용, API 키 없이 동작)
  - `generateAIResponse()` 3단계 로직: ① 지역 미수집 시 질문 → ② DEMO_MODE + 지역 수집 시 하드코딩 응답 → ③ RAG/FAQ 폴백
- **크롤러 카테고리 선택 옵션** (`scripts/crawl_hscity.py`): `--category` 인자 추가로 특정 카테고리만 크롤링 가능
- **교통·차량 RAG 데이터** (`data/hscity_output/hscity_rag.jsonl`): 교통·차량 카테고리 36개 문서 추가 크롤링 (세정 27 + 교통 36 = 총 63개)

### 변경
- `processUtterance()`: 지역 수집 단계(`collectingInfo=true`)일 때 `handleDistrictCollection()`으로 우선 분기
- `triggerRouting()`: 민원 분류 완료 후 바로 연결하지 않고, `COMPLAINT_INFO_NEEDS`에 해당 유형이 있으면 지역 질문 선행
- `resetRoutingBrief()`: 초기화 시 `collectingInfo`, `collectComplaintType`, `collectedDistrict` 상태 리셋 추가

---

## [2026-08-14] — 악성 민원 관리 강화 · 안정성 개선

### 추가
- **블랙리스트 관리 탭** (`/admin`): 악성 민원인 전체 목록, 전과 횟수, 통화 제한 상태, 삭제 기능
- **블랙리스트 API** (`GET /admin/blacklist`, `DELETE /admin/blacklist/{phone}`): 전체 목록 조회 및 개별 삭제
- **AI 전환 시 자동 DB 저장**: AI 상담으로 전환될 때 이름·전화번호를 자동으로 블랙리스트에 기록 (기존: 담당자 수동 조회 필요)
- **AI 전환 시 6개월 이력 자동 확인**: 전환과 동시에 전과 횟수 조회 후 통화 제한 카운트다운 자동 시작

### 변경
- **2회 전과 통화 제한 시간**: 3시간 → **6시간**
- **제한 기준** (6개월 내 누적): 1회→1시간 / 2회→6시간 / 3회 이상→24시간
- **긴급도 라벨**: AI 민원 분석 카드의 "위험도" → "긴급도" (민원인 악성도와 혼동 방지)
- **TTS 순차 재생**: `speak()` 함수가 Promise를 반환하도록 변경 → 이전 음성이 완전히 끝난 후 다음 음성 재생 (겹침 문제 해결)
- **통화 시작 버튼 수정**: `recognition.start()`를 TTS 이전에 직접 호출 → 브라우저가 TTS를 차단해도 STT 정상 동작
- **`resetStats()` 오류 수정**: 삭제된 반복발화 DOM 요소(`cnt-repeat`, `repetition` 바) 참조로 인한 크래시 수정

### 제거
- `speak()` 내부 `recognition.stop()` 제거 → `suppressSTT` 플래그만으로 피드백 루프 차단 (TTS 중 STT 결과 무시)
