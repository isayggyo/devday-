# DevDay Seoul 2026

2026년 10월 9일 DevDay Community Hackathon Seoul 작업 저장소입니다.

- 저장소: https://github.com/isayggyo/devday-
- 브랜치: `main`
- 로그 수집 시작: **2026-10-09 10:28:01 KST**
- 작업 경과: [docs/work-log.md](docs/work-log.md)

## 웹앱 스모크 E2E

```powershell
python scripts/setup_e2e.py
python scripts/local_postgres.py start
python scripts/local_storage.py start
python scripts/migrate.py
python scripts/run_e2e.py --runs=3
```

Puppeteer + `~/.cache/gyeol-cft`의 Chrome for Testing으로 실행합니다.
실제 마이크 대신 고정 강의 WAV와 테스트 PDF를 사용합니다.
영속 세션·PDF/PPT 분석·브라우저 녹음/백업·실시간 전사·Live Notes·시점 고정 Q&A·선택적 시각 설명을 제공합니다.
사용자 요청으로 Step 10 최종 슬라이드·종료 후 합성에는 착수하지 않습니다.
기존 8단계 스모크에서 최종 슬라이드와 세션 종료는 `NOT_IMPLEMENTED`와 종료 코드 1을 반환합니다.
결과는 `artifacts/e2e/`에 보존합니다.
[실행법·검증 조건·앱 연결 계약](docs/e2e.md)을 확인하세요.

웹앱 개발 환경 설치·실행은 [로컬 개발 안내](docs/local-development.md),
단계별 구현·테스트 결과는 [Phase 1 진행 기록](docs/phase1-progress.md)을 참고하세요.

Step 9까지의 실제 AI 브라우저 검증은 별도로 실행합니다. 백엔드에 OpenAI 키가 필요합니다.

```powershell
python scripts/run_lecture_e2e.py --runs=3
```

원본 녹음·실제 전사·노트·질문 Snapshot·답변·시각 설명·출처·녹음 중지까지 검증하며,
Step 10은 실행하지 않습니다. 단계별 시간·콘솔/API 오류·스크린샷은 `artifacts/phase1/`에 보존합니다.

## Codex 작업 로그

Python 표준 라이브러리만 사용합니다. 이 프로젝트의 Codex 세션에서 시작
시점 이후 사용자 요청, 공개 응답, 도구 실행 및 결과를 로컬에 수집합니다.
모델의 비공개 추론과 시스템·개발자 지시문은 수집 대상에서 제외합니다.
원본 세션 파일은 수정하지 않습니다.

```powershell
python scripts/codex_logs.py start    # 5초 간격 백그라운드 수집 시작
python scripts/codex_logs.py status   # 동작 상태와 수집량 확인
python scripts/codex_logs.py collect  # 즉시 동기화
python scripts/codex_logs.py export   # logs/exports/에 ZIP 생성
python scripts/codex_logs.py stop    # 백그라운드 수집 중지
```

원본 위치는 `CODEX_HOME` 또는 사용자 홈의 `.codex/sessions`입니다.
수집본은 `logs/codex/`, 설정과 실행 상태는 `logs/runtime/`에 저장합니다.
새 대화도 작업 폴더가 이 저장소 또는 그 하위 폴더이면 수집됩니다.
PC 재시작 후에는 `start`를 다시 실행합니다. 중지된 동안에도 Codex 원본이
남아 있으면 다시 시작할 때 해당 기간을 수집합니다.

생성한 ZIP은 로컬 작업 기록 백업입니다. 참가 가이드 4쪽에 따르면 공식
로그 내보내기 방법과 파일 제한은 팀장에게 따로 안내됩니다. 그 안내를
받으면 제출 형식을 맞추고, 제출 전 비밀 키·개인정보 포함 여부를 확인합니다.

## 참가 가이드에서 확인한 제출 기준

출처: `DevDay_Seoul_Participant_Guide.pdf`, 3–4쪽.

- 2026-10-09 **17:00 KST**까지 플랫폼 제출과 GitHub `main` 반영 완료.
- GitHub 저장소 URL, 발표 PDF, 데모·참고 링크, 팀원별 Codex 기록 ZIP 준비.
- 사전 작업과 당일 작업, 외부 자료의 출처와 활용 범위를 구분해 기록.
