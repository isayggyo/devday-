# Local development

Windows에서는 도구와 의존성을 프로젝트 안에 설치합니다. Python 3.11+,
Node 22.12+ 및 기존 `~/.cache/gyeol-cft`의 Chrome for Testing을 사용합니다.
PostgreSQL/S3 데이터와 자격 증명은 Git에 포함되지 않습니다.

```powershell
python scripts/setup_e2e.py
python scripts/material_tools.py storage
python scripts/material_tools.py libreoffice
python scripts/local_postgres.py start
python scripts/local_storage.py start
python scripts/migrate.py
python scripts/migrate.py --test
python scripts/dev.py start
```

`http://127.0.0.1:3000`에서 강의를 만들고 PDF/PPT/PPTX 자료를 업로드합니다.
자료 분석은 최대 2분까지 걸릴 수 있습니다. 페이지를 선택하고 원본을 다시 열 수 있습니다.
마이크 녹음을 시작하면 자막과 요약 노트가 갱신됩니다. 질문 영역에서 사용할 자료 페이지를
선택하고 질문합니다. 답변의 근거를 펼쳐 전사 구간·자료 페이지를 확인할 수 있습니다.
필요하면 비교표·흐름도·개념도·수식·텍스트 시각 설명을 요청합니다. 생성 오류가 발생해도
텍스트 답변과 녹음은 유지됩니다. 녹음 중지는 원본 업로드와 전사 확정을 기다립니다.
최종 슬라이드·강의 전체 합성·PDF 내보내기는 Step 10으로, 요청에 따라 구현하지 않습니다.
로그는 `artifacts/dev`, `artifacts/infra`에 저장됩니다.

```powershell
python scripts/dev.py stop
python scripts/local_storage.py stop
python scripts/local_postgres.py stop
```

개발 서버 시작은 버전 마이그레이션을 적용하고 실제 DB 및 프론트→백엔드
연결을 검사합니다. 종료 시 기록한 PID·생성 시각·실행 파일이 모두 일치하는
서버만 종료합니다. PostgreSQL과 S3 저장소는 별도 종료 명령을 사용합니다.

```powershell
python scripts/test_phase.py --step=9
python scripts/test_harness.py
python scripts/run_lecture_e2e.py --runs=3
python scripts/run_e2e.py --runs=3
```

단계별 검증 결과는 `docs/phase1-progress.md`에 기록합니다.
스모크는 기능이 아직 없으면 NOT_IMPLEMENTED로 끝나며 종료 코드는 1입니다.
`run_lecture_e2e.py`는 Step 9까지의 실제 AI 흐름만 검증합니다. 질문 중 원본 녹음·STT·노트
갱신, 고정 Snapshot의 인용, 실제 Responses 시각 설명을 검사합니다. 각 run은 별도 사용자·
세션·Chrome 프로필로 시작하며 생성한 테스트 데이터와 앱 서버를 정리합니다.

`NOTE_MIN_SEGMENTS`·`NOTE_INTERVAL_SECONDS`로 노트 배치 간격을 조절합니다.
`CONTEXT_WINDOW_SECONDS`는 120–300초이며 기본 180초입니다. 전사 원본과 선택한 자료를
질문 등록 시 복사해 고정합니다. 이후 새 전사나 자료 변경이 답변 근거에 섞이지 않습니다.
중단된 답변/시각/노트 작업은 UI에서 재시도할 수 있으며 실행 중으로 남은 작업은
90초 이후 재시도할 수 있습니다. 서버 재시작 시 작업을 자동 복구하는 큐는 제공하지 않습니다.

인증은 로컬 개발용 임시 사용자입니다. API의 `X-Dev-User-Id`는 테스트에서
사용자 격리를 검증하기 위한 값이며 운영 인증이 아닙니다. `APP_ENV=production`에서
개발 인증을 사용할 수 없고, 현재 JWT 모드를 선택하면 검증 미구현으로 401을 반환합니다.
OpenAI 키는 백엔드의 `OPENAI_API_KEY` 환경변수에 설정하며 브라우저로 전달하지 않습니다.

다른 운영체제에서는 실제 PostgreSQL과 S3 호환 저장소 및 LibreOffice를 준비한 뒤
`.env.example`을 참고하여 `.env`를 작성합니다. `LIBREOFFICE_PATH`는 해당 실행 파일의 경로입니다.
Windows 다운로드는 공식 배포 URL과 SHA-256을 고정해 검증하며 LibreOffice는 시스템 설치 없이 파일만 추출합니다.
