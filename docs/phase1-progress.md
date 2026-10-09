# Phase 1 진행 기록

사용자 명세의 Step 0 → 12 순서를 따릅니다. 구현·단위/통합 테스트·실행·수정·기록을
단계별로 완료하고 진행합니다. 시각은 KST입니다.

| Step | 작업 | 상태 |
| --- | --- | --- |
| 0 | 저장소와 기존 하네스 점검 | 완료 |
| 1 | 프로젝트 기반, PostgreSQL, 환경 설정, 프론트/백 통신 | 완료 |
| 2 | 사용자별 영속 강의 세션 | 진행 중 |
| 3 | PDF/PPT 자료 저장·페이지 분석·표시 | 대기 |
| 4 | 녹음·IndexedDB 백업·업로드·재시도 | 대기 |
| 5 | 실제 OpenAI 실시간 전사 | 대기 |
| 6 | 확정 전사 기반 Live Notes | 대기 |
| 7 | ContextProvider·고정 Snapshot | 대기 |
| 8 | 비동기 학생 Q&A | 대기 |
| 9 | 선택적 시각 설명 | 대기 |
| 10 | 종료 후 최종 슬라이드·PDF | 대기 |
| 11 | 통합 화면·복구 UI | 대기 |
| 12 | 최종 안정화·반복 E2E | 대기 |

## Step 0 — 2026-10-09 12:12

- 완료: 파일 구조, 앱 미구현 상태, 의존성·환경 변수·실행 명령 확인.
- 재사용: `frontend/`, `backend/`, `e2e/`, 고정 PDF·52.98초 WAV, Node 실행기, 로그 수집기.
- 기존 검증: `python scripts/run_e2e.py --runs=3`; 1~2단계 PASS,
  3~8단계 NOT_IMPLEMENTED, 정상적인 종료 코드 1.
- 하네스 검증: `python scripts/test_harness.py`; 실제 Chrome 오류/마이크 관찰을
  포함한 12개 테스트 통과.
- 원본 결과: `artifacts/e2e/2026-10-09T02-51-57-256Z-a4654c70/summary.json`.
- 제한: 현재 세션은 메모리 저장이며 실제 자료·녹음·AI 생성은 미구현.
  PostgreSQL, Object Storage, LibreOffice가 설치돼 있지 않고 DB 환경 변수도 없음.
- 최소 변경: PostgreSQL 개발 환경, TypeScript, 환경 설정과 DB 마이그레이션을
  먼저 추가. 자료 처리 및 AI 의존성은 해당 Step에서 추가.
- 새 명세 반영: 최종 슬라이드는 강의 종료 후 생성하도록 기존 E2E 순서를
  적절한 단계에서 수정. 강의 중에는 Live Notes와 질문에 필요한 시각 설명만 생성.
- 로컬 자격 증명 파일은 Git 제외 처리. 키 값은 프론트엔드나 기록에 노출하지 않음.
- 다음: Step 1 실제 PostgreSQL 연결과 프론트/백 통신 검증.

## Step 1 — 2026-10-09 12:36

- 구현: Next.js TypeScript 전환, FastAPI 설정/표준 오류/요청 ID, 실제 PostgreSQL 17.11 연결, 프론트엔드 서버 프록시와 연결 표시.
- 로컬 실행: `python scripts/local_postgres.py start`, `python scripts/dev.py start [--e2e]`, `python scripts/dev.py stop`.
- Windows 한글 경로는 같은 프로젝트를 가리키는 임시 영문 junction으로 참조. DB 데이터와 비밀번호는 무시되는 프로젝트 infra/data 및 .env에 보관.
- 검증: `python scripts/test_phase.py --step=1` — 백엔드 6개, 프론트엔드 2개, TypeScript 검사, 실제 Chrome 통신 모두 PASS.
- 브라우저 결과: `artifacts/phase1/step1-1791516787398/result.json` 및 foundation.png.
- 개발 서버 실제 시작/헬스체크/신원 확인 후 트리 종료 PASS. Windows detached 실행 실패를 숨김 창 실행으로 수정.
- 한계: 개발용 인증만 제공. 운영 인증과 실제 AI 연동은 검증되지 않았으며 세션은 아직 메모리 저장.
- 다음: Step 2 DB 마이그레이션, 영속 세션 및 사용자 격리.
