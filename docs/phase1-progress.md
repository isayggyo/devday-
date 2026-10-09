# Phase 1 진행 기록

사용자 명세의 Step 0 → 12 순서를 따릅니다. 구현·단위/통합 테스트·실행·수정·기록을
단계별로 완료하고 진행합니다. 시각은 KST입니다.

| Step | 작업 | 상태 |
| --- | --- | --- |
| 0 | 저장소와 기존 하네스 점검 | 완료 |
| 1 | 프로젝트 기반, PostgreSQL, 환경 설정, 프론트/백 통신 | 완료 |
| 2 | 사용자별 영속 강의 세션 | 완료 |
| 3 | PDF/PPT 자료 저장·페이지 분석·표시 | 완료 |
| 4 | 녹음·IndexedDB 백업·업로드·재시도 | 완료 |
| 5 | 실제 OpenAI 실시간 전사 | 완료 |
| 6 | 확정 전사 기반 Live Notes | 완료 |
| 7 | ContextProvider·고정 Snapshot | 완료 |
| 8 | 비동기 학생 Q&A | 완료 |
| 9 | 선택적 시각 설명 | 완료 |
| 10 | 종료 후 최종 슬라이드·PDF | 추가 요청으로 최소 개인화·응용 문제 통합 완료 |
| 11 | 통합 화면·복구 UI | 이번 요청 범위 밖 |
| 12 | 최종 안정화·반복 E2E | 이번 요청 범위 밖 |

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

## Step 2 — 2026-10-09 12:45

- 구현: LectureSession의 필수 필드와 7개 상태, Alembic 0001 마이그레이션, PostgreSQL 영속 세션, POST/GET/list API와 준비/실패 변경 API.
- 상태 전환은 행 잠금과 허용 전환표로 검증. 녹음·처리·완료 상태는 실제 파이프라인이 변경하도록 분리.
- 모든 세션 접근에서 사용자 소유권 확인. 개발용 임시 사용자 표시, 운영 인증 선택 시 임시 사용자로 폴백하지 않고 401.
- UI에서 제목 입력·생성·목록·다시 열기, 로딩·오류·재시도 제공. 기존 E2E 세션도 DB에 저장하고 테스트 표시된 세션만 삭제.
- 검증: `python scripts/migrate.py`, `python scripts/migrate.py --test`, `python scripts/test_phase.py --step=2`.
- 결과: 백엔드 12개, 프론트엔드 2개, 타입 검사 PASS. 실제 Chrome에서 생성 후 프론트/백엔드를 모두 종료·재시작하고 동일 강의 복원 PASS, 테스트 세션 삭제 확인.
- 브라우저 결과: `artifacts/phase1/step2-1791517421641/result.json` 및 persistent-session.png.
- 초기 React 준비 전 입력과 의도된 재시작 중 HMR 연결 오류를 브라우저 준비 대기/페이지 종료로 수정. 프로세스 종료 알림 경합을 수정하고 하네스 12개 재검증 PASS.
- 한계: 운영 JWT 검증은 제공하지 않음. 자료·녹음·AI는 다음 단계 대상.
- 다음: Step 3 실제 Object Storage와 PDF/PPT 파싱, 첫 Vertical Slice.

## Step 3 — 2026-10-09 13:05

- 구현: 실제 SeaweedFS 4.48 S3 호환 Object Storage, PyMuPDF PDF 파싱, 실제 LibreOffice 26.2.6 PPT/PPTX 변환. 배포 URL·SHA-256 고정, 도구는 프로젝트 안에만 추출.
- MaterialDocument/MaterialPage와 0002 DB 마이그레이션. 원본·변환 PDF·페이지 PNG·추출 이미지 바이너리는 Object Storage, 텍스트·표·텍스트 span·벡터·페이지 정보는 DB 저장.
- 파일 형식·크기·페이지 수·암호화 검증, textless 페이지 needs_analysis, 처리 실패 상태 및 원본 보존 후 재시도. 모든 자료 API에서 세션 소유권 확인.
- UI: 세션 생성 → PDF/PPT/PPTX 업로드 → 원본 열기·페이지 이동·이미지·추출 텍스트 표시, 로딩·실패·재처리.
- 검증: `python scripts/test_phase.py --step=3` — 백엔드 26개, 프론트엔드 2개, 타입 검사 PASS. 실제 PDF 2페이지/PPTX 2페이지, legacy PPT→PDF, 표·수식 원본 표현, textless, 원본 해시, 사용자/세션 격리, 저장소 장애·실제 재시도 검증.
- Chrome에서 PDF/PPTX 업로드·페이지 이동·새로고침 후 복원 PASS. 원본 SHA-256 일치, 브라우저 오류 없음, 테스트 세션·객체 삭제.
- 결과: `artifacts/phase1/step3-1791518497742/result.json` 및 material-pages.png.
- Windows Installer 추출이 대기해 lessmsi 파일 추출로 변경. LibreOffice 최초 로딩·변환은 수십 초 소요될 수 있으며 최대 120초로 제한.
- 한계: OCR/시각 AI 분석은 제공하지 않음. 추출 불가능한 페이지는 명시적으로 추가 분석 필요 상태. 최종 슬라이드·전사는 미구현.
- 다음: Step 4 실제 브라우저 녹음, IndexedDB 백업과 서버 전송·재시도.
- 3회 스모크 재검증: 모든 run의 1~3단계 PASS, 4~8단계 NOT_IMPLEMENTED. 세션 격리·객체/세션 삭제 PASS, 최종 종료 코드 1(예상). `artifacts/e2e/2026-10-09T04-03-41-531Z-a6d9b38a/summary.md`.

## Step 4 — 2026-10-09 13:23

- 구현: 실제 getUserMedia/MediaRecorder 녹음, 권한·장치 안내/선택, IndexedDB 원본 청크와 전송 여부 보관, 서버 S3 백업 및 원본 재조회.
- AudioChunk 0003 마이그레이션. 안정된 청크 ID·순서·시간·SHA-256으로 재전송 중복 방지, 같은 순서/다른 내용 충돌 거부, 세션 소유권 확인.
- 녹음 시작·중지·마지막 청크 저장·마이크 해제, 재시도·로컬 내려받기. 원본 백업 경로와 향후 실시간 STT 연결 callback 분리.
- 장치 종료·mute·화면 숨김·타이머 지연/절전·페이지 이탈을 감지하고 중단 상태 표시. 새로고침 후 미전송 청크 복구 및 서버 녹음 상태 중지 가능.
- 검증: 백엔드 33개, 프론트엔드 4개, TypeScript 검사 PASS. 동시 청크 재전송·내용 충돌·저장소 장애 후 재시도·실제 WAV 바이너리 왕복 검증.
- 실제 Chrome 두 환경에서 권한 거부와 고정 WAV getUserMedia 녹음 검증. 강제 네트워크 단절 동안 녹음 지속 및 IndexedDB 미전송 보존, 재연결 후 실제 전송, 중복 방지, 마지막 청크·마이크 해제, 새로고침 보존 PASS.
- S3에서 내려받은 실제 WebM과 IndexedDB 원본의 전체 SHA-256 일치. 4개 실제 청크/98,512바이트. 결과: `artifacts/phase1/step4-1791519695068/result.json`.
- 의도된 offline 오류 9개는 별도 단계로 기록·검증. 그 외 브라우저 오류 없음. 기존 하네스 12개 재검증 PASS.
- 수정: React 형제 컴포넌트 키 중복, UTC 시간 응답 통일. 권한 거부 환경에만 자동 허용 플래그를 해제하고 실제 거부를 확인.
- 한계: 물리 노트북 마이크와 실제 OS 절전은 수동 검증하지 못함. 고정 WAV를 실제 브라우저의 MediaStream/MediaRecorder에 입력해 검증했으며, 페이지 종료 직전 데이터의 절대 보존을 보장하지 않음.
- 다음: Step 5 공식 최신 API 규격에 맞춘 실제 OpenAI 실시간 전사·순서/중복/재연결.

## Step 5 — 2026-10-09 13:43

- 최신 공식 전사 가이드 확인: gpt-live-transcribe, 24kHz PCM, 클라이언트 발화 종료 commit, type=transcription 세션. 실제 모델 접근 200 및 WebSocket 설정 승인 확인.
- AudioWorklet 실시간 PCM 경로를 원본 MediaRecorder 백업과 분리. 백엔드가 OpenAI와 연결하며 브라우저에는 60초 단일 사용·소유권 지정 릴레이 티켓만 전달.
- 부분 전사는 화면에만 표시. commit 시 순서를 예약하고 실제 provider 확정 이벤트만 TranscriptSegment로 저장. 타임스탬프·revision·committedAt 보존, 중복·순서 뒤바뀜·확정 전 충돌 처리.
- 재연결 시 최근 미확정 PCM을 재전송하고 확정된 구간은 제외. 전사 실패가 원본 녹음을 중지하지 않음. 중지 시 최종 발화 확정 대기 및 소켓 종료.
- 검증: 결정적 이벤트 단위 테스트와 실제 AI 검증을 분리. 전사/녹음/기반/세션 22개 테스트 PASS, TypeScript 검사 PASS.
- 실제 Chrome/고정 WAV/OpenAI에서 확정 자막 3개 수신·DB 저장·시간/순서·재연결 중 녹음 유지 PASS. 자막 내용은 실제 인출 연습/기억 강의 음성에 해당하며 가짜 텍스트를 주입하지 않음.
- 결과: `artifacts/phase1/step5-1791520820227/result.json`, real-transcription.png. 전사 API 공개 POST는 허용하지 않으며 단일 사용 티켓·만료·소유권 검증 PASS.
- 한계: 물리 마이크 수동 검증은 미실시. 재연결 PCM 버퍼는 약 20초로 제한되며 장기 단절 시 누락 가능성을 표시하고 원본 음성은 유지.
- 다음: Step 6 발화 누적 기반 Live Notes.

## 범위 변경 — 2026-10-09 13:43

- 사용자 요청: Step 9까지 구현·검증 후 멈춤. Step 10 최종 슬라이드 생성에는 착수하지 않음.

## Step 6 — 2026-10-09 13:52

- 확정 전사를 실제 Responses API로 요약하고 ID·인용 구절을 검증. 영속 revision·실패 재시도 UI 구현.
- Mock 경계 테스트 2개 PASS. 실제 Chrome/AI 테스트: 4개 확정 자막, 출처가 연결된 Live Note, 재연결 중 녹음 유지 PASS.
- 결과: `artifacts/phase1/step5-1791521226181/result.json`.
- 이후 조용한 발화 구간에서도 20초 배치 마감, 늦게 확정된 발화 누락 방지 보강.

## Step 7 — 2026-10-09 13:56

- Immutable ContextSnapshot + WindowContextProvider interface. Confirmed transcript window (default 180 seconds), selected material pages and secondary rolling notes; evidence copied at registration, primary/secondary evidence separated.
- Real PostgreSQL tests: 3 PASS (future/changed transcript, selected page version and ownership, insufficient context). Both databases migrated to 0006_context.
- Next: Step 8 asynchronous, deduplicated grounded Q&A.

## Step 8 — 2026-10-09 14:02

- 질문·고정 Snapshot·답변을 DB에 저장. 독립 작업 스레드에서 ContextProvider를 거쳐 실제 Responses 답변 생성. clientQuestionId 중복/충돌, 인용 ID·버전·본문 검증, 근거 부족·실패 재시도 구현.
- DB 경계 테스트 3개와 타입 검사 PASS. 실제 Chrome 테스트 PASS: 자료 선택, 실제 답변/인용, 재전송 중복 방지, 질문 중 녹음·전사·노트 revision 갱신.
- 결과: `artifacts/phase1/step5-1791522059507/result.json`. 근거 부족 실제 응답은 `step5-1791521950335/result.json`에 보존.
- 발견한 PDF 공백 비교 assertion과 Uvicorn 로그 포맷 오류 수정. 로그 비밀 티켓 마스킹 회귀 테스트 PASS.
- 다음: Step 9 선택적 시각 설명. Step 10 미착수 유지.

## Step 9 — 2026-10-09 14:31

- 실제 Responses Structured JSON 기반 선택적 시각 설명. equation·comparison·flowchart·concept_diagram·text_explanation 지원. 답변과 별도 작업으로 생성하고 ID·출처·revision·실패 상태를 저장.
- React/SVG/KaTeX 렌더러, 비교 열·그래프 노드/간선·출처 검증, JSON/수식 실패 시 텍스트 답변 유지 및 재시도 구현. 모든 답변에 자동 생성하지 않으며 사용자가 형식을 골라 요청할 수 있음.
- 전체 백엔드 55개, 프론트엔드 7개, 기존 하네스 12개, TypeScript 검사 및 Next.js 프로덕션 빌드 PASS.
- 최종 실제 AI/Chrome 반복: `python scripts/run_lecture_e2e.py --runs=3` → 3/3 PASS. 자료 선택·전사·노트 갱신·질문 Snapshot·실제 답변·비교표·인용·녹음 중지·청크 저장·세션 정리 확인.
- 결과: `artifacts/phase1/step9-suite-1791523870307/summary.json`. 가짜 자막·슬라이드·답변을 앱에 주입하지 않음. Mock 테스트와 실제 AI 결과를 분리.
- 보존한 실패: 첫 시각 응답 검증 실패(`step9-1791522574428`), 테스트 중 소스 수정/자동 갱신과 겹친 녹음 중지 실패(`step9-1791523054238`), 소스 고정 반복에서도 원본 청크가 없는 실행(`step9-1791523294917`). 독립 Native MediaRecorder/AudioWorklet/IndexedDB 진단은 작업/임시 경로 모두 6/6 PASS. 마지막 현상의 원인은 확정하지 못했으며 최초 청크 필수 확인·실패 상태 수집으로 잘못된 PASS를 차단.
- 제한: 실제 AI 브라우저 시각 검증은 비교표를 대상으로 함. 수식·흐름도·개념도·텍스트 및 실패 대체는 스키마/실제 React 렌더링 단위 테스트로 검증. 물리 마이크·OS 절전 수동 테스트는 미실시. 로컬 개발 인증이며 운영 JWT와 자동 작업 큐 복구는 미구현.
- 요청대로 Step 9에서 중단. Step 10 최종 슬라이드·합성·PDF 내보내기는 착수하지 않음.
- 기존 스모크 최종 재검증: `python scripts/run_e2e.py --runs=3` → 모든 run의 1–5단계 PASS, 6–8단계 NOT_IMPLEMENTED(제외한 최종 슬라이드/세션 완료). 콘솔/API 오류 0, 모든 정리 단계 PASS, 의도한 종료 코드 1. `artifacts/e2e/2026-10-09T05-32-25-812Z-5be131ec/summary.md`.
