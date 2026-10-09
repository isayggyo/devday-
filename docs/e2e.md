# 강의 웹앱 스모크 E2E

Puppeteer가 로컬 Next.js 프론트엔드와 FastAPI 백엔드를 직접 실행하고,
실제 Chrome for Testing에서 8단계 시나리오를 검증합니다. 현재 앱은
실제 PostgreSQL의 세션 관리와 S3 저장소의 자료 업로드·페이지 분석을 제공합니다. 자막과 슬라이드를
주입하거나 API를 성공 응답으로 대체하지 않습니다.

## 실행

Python 3.11+와 Node 22.12+가 필요합니다. 이 PC에서는 PATH 밖에 있는
기존 Node 런타임도 Python 실행기가 찾습니다. 다른 환경에서는 Node를
PATH에 두거나 `E2E_NODE`에 실행 파일 경로를 지정합니다.

```powershell
python scripts/setup_e2e.py
python scripts/local_postgres.py start
python scripts/material_tools.py storage
python scripts/local_storage.py start
python scripts/migrate.py
python scripts/run_e2e.py --runs=3
```

일반 Node/npm 환경에서는 `npm ci`와 Python 가상환경의
`pip install -r backend/requirements.lock.txt`로 설치한 뒤 다음과 같이 실행할 수 있습니다.

```powershell
npm run e2e -- --runs=3
```

의존성은 프로젝트의 `node_modules`, `.venv`, `.tools`에만 설치합니다.
JS는 `package-lock.json`, Python은 `backend/requirements.lock.txt`로 고정합니다.
Chrome을 다운로드하지 않으며 `~/.cache/gyeol-cft`에서 실행 파일을 찾습니다.
필요하면 `--chrome=절대경로` 또는 `E2E_CHROME`으로 지정합니다.

기본 URL은 프론트엔드 `http://127.0.0.1:3000`, 백엔드
`http://127.0.0.1:8000`입니다. 각 run에서 서버를 시작하고 종료합니다.
포트가 사용 중이면 실패합니다. 직접 실행한 개발 서버에 연결하려면
백엔드를 `E2E_MODE=1`로 실행하고 `--attach`를 사용합니다. 이 경우 하네스는
기존 서버를 종료하지 않습니다.

```powershell
python scripts/run_e2e.py --runs=3 --frontend-url=http://127.0.0.1:3100 --backend-url=http://127.0.0.1:8100
python scripts/run_e2e.py --runs=3 --attach
python scripts/run_e2e.py --runs=1 --headed --timeout-ms=60000
python scripts/test_harness.py
```

단계 대기는 기본 30초, 서버 기동과 브라우저 실행 대기는 60초입니다.
`--startup-timeout-ms`로 기동 대기를 바꿀 수 있습니다.

## 오디오와 자료 fixture

`e2e/fixtures/lecture.pdf`는 2페이지 영문 강의자료입니다. 주제는 retrieval
practice, spaced repetition, cognitive load이며 텍스트는 이 프로젝트에서
작성했습니다. `lecture.wav`는 같은 내용을 Microsoft Zira Desktop으로
읽은 **52.98초, 16 kHz, 16-bit PCM mono** 음성입니다. 실제 마이크가 필요하지 않습니다.

Chrome 실행 인자는 다음과 같습니다.

```text
--use-fake-ui-for-media-stream
--use-fake-device-for-media-stream
--use-file-for-fake-audio-capture=<lecture.wav의 절대경로>
```

각 run은 새 Chrome 프로세스를 사용하여 파일 입력과 브라우저 저장 상태를
새로 시작합니다. 실행 전 별도 로컬 진단 페이지에서 실제 `getUserMedia`와
`MediaRecorder`로 3초를 캡처하고, 음성 에너지·캡처 크기·트랙 해제를 확인합니다.
진단은 앱의 녹음 단계 통과로 계산하지 않습니다.

`lecture.json`의 PDF/WAV SHA-256과 실제 파일을 비교합니다. 음성이 없거나,
무음 WAV이거나, 파일이 달라지면 실패합니다. Fixture를 변경할 때는
`lecture.txt`와 `lecture.json`의 페이지 내용을 함께 바꾸고 다음을 실행합니다.
PDF 재생성에만 `reportlab`이 필요하며 일반 E2E 실행에는 필요하지 않습니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/generate_audio_fixture.ps1
python scripts/generate_pdf_fixture.py
```

## 단계별 통과 조건

| 단계 | 확인하는 실제 동작 |
| --- | --- |
| 1 | 서버 기동, 각각의 헬스체크, 빈 테스트 세션 생성·조회 |
| 2 | 실제 앱 페이지 로드, 테스트 세션 연결, 이전 PDF·전사·슬라이드 없음 |
| 3 | PDF file input 업로드, 백엔드 파일명/SHA-256과 표시된 문서 ID 일치 |
| 4 | 시작 버튼, 실제 live 마이크 트랙, 백엔드에 0보다 큰 오디오 바이트 |
| 5 | 비어 있지 않은 자막 1개 이상, 해당 전사 ID·텍스트·세션이 백엔드와 일치 |
| 6 | 실제 텍스트와 SVG/이미지/캔버스가 렌더링된 시각 슬라이드 1장 이상, 저장된 슬라이드 ID 일치 |
| 7 | 화면과 저장된 제목/본문 일치, 실제 전사 참조, PDF 파일명·페이지·원문 인용 및 표시 출처 확인 |
| 8 | 중지 버튼, 마이크 트랙 해제, 녹음기 inactive, 백엔드 stopped, UI/백엔드 ended, API WebSocket 종료 |

각 단계는 `PASS`, `FAIL`, `NOT_IMPLEMENTED`, `BLOCKED`로 기록합니다.
백엔드가 기능을 미구현으로 선언하거나 API가 HTTP 501을 반환하면
`NOT_IMPLEMENTED`입니다. 구현되었다고 선언한 기능이 조건을 만족하지
않으면 assertion으로 `FAIL` 처리합니다. 앞 단계의 필수 결과가 없으면
`BLOCKED`와 이유를 기록합니다. 전체 시나리오가 모두 통과할 때만 종료 코드가
**0**입니다. 미구현·차단·오류는 모두 **1**, CLI 인자 오류는 **2**입니다.
누적 중인 실시간 전사 텍스트는 동일 ID의 UI/백엔드 중 한쪽이 다른 쪽의
접두사인 경우도 일치로 봅니다. 슬라이드는 실제 시각 요소가 렌더링될 때까지 대기합니다.

녹음 종료 단계는 전사나 슬라이드 단계의 실패와 관계없이 시도합니다.
그 이후 `finally`에서 잔여 트랙 해제, 브라우저 종료, 테스트 세션 삭제와
404 확인, 하네스가 시작한 서버 종료를 수행합니다. 이 강제 정리는
8단계의 정상 종료를 통과한 것으로 계산하지 않습니다.

## 앱 구현 시 유지할 계약

현재 기능 상태는 `backend/app.py`의 `CAPABILITIES`에서 모두 `false`입니다.
실제 기능을 구현한 뒤 해당 값을 `true`로 바꾸고 아래 UI/API를 연결하면
하네스가 자동으로 해당 단계를 검증합니다. 데이터는 실제 업로드·오디오·전사·
생성 결과에서 나와야 합니다. 테스트에서는 결과를 만들어 주지 않습니다.

| API | 계약 |
| --- | --- |
| `GET /health` | `{status:"ok", service:"lecture-backend", e2e_enabled:true}` |
| `GET /api/capabilities` | `upload`, `recording`, `transcription`, `slides`, `provenance`, `session_end`의 boolean |
| `POST /api/e2e/sessions` | `{run_id}` 입력, HTTP 201, 독립된 빈 세션 반환 |
| `GET /api/sessions/{id}` | `id`, `run_id`, `state`, `documents`, `transcripts`, `slides`, `audio_bytes` |
| `DELETE /api/e2e/sessions/{id}` | 해당 세션의 모든 실제 상태·파일 제거, HTTP 204; 이후 조회 404 |
| `GET /api/sessions/{id}/transcripts` | 실제 전사 배열: `{id, session_id, text}` |
| `GET /api/sessions/{id}/slides` | 실제 슬라이드 배열: `{id, session_id, ...}` |
| `GET /api/sessions/{id}/slides/{slideId}` | 아래 출처 검증 스키마 |

프론트엔드 `GET /api/health`는 `{status:"ok", service:"lecture-frontend"}`를
반환합니다. 앱 URL의 `?session=<id>`를 실제 세션에 연결합니다.
업로드·녹음 시작/중지·종료 요청의 경로는 앱 구현에 맞춰 바꿀 수 있습니다.
하네스는 버튼 동작과 결과 상태를 검사합니다. 업로드된 문서의
`documents` 항목에는 `id`, `filename`, 실제 파일의 `sha256`이 필요합니다.

슬라이드 상세 스키마:

```text
id, session_id, title, body, document_id,
transcript_ids: [실제 같은 세션의 전사 ID],
sources: [{ document_id, filename, page: 1부터 시작하는 정수, excerpt: PDF 해당 페이지의 실제 원문 }]
```

슬라이드 제목·본문은 비어 있으면 안 됩니다. 원문 인용은 정규화 후
12자 이상이고 fixture의 해당 페이지에 존재해야 합니다. 의미 품질 전체에
대한 평가가 아니라, 내용을 실제로 표시하고 전사·자료 출처를 추적할 수
있는지를 검사합니다.

| `data-testid` | 필수 속성/표시 |
| --- | --- |
| `lecture-app` | 앱의 표시된 루트 |
| `session-state` | `data-session-id`, `data-state`: idle → recording → stopped → ended |
| `lecture-pdf-input`, `lecture-upload` | file input과 업로드 버튼 |
| `lecture-document` | `data-document-id`, `data-filename`, 표시된 파일명 |
| `recording-start`, `recording-stop`, `session-end` | 실제 동작 버튼 |
| `transcript-item` | `data-transcript-id`, `data-session-id`; 자식 `transcript-text`에 전사 텍스트 |
| `generated-slide` | `data-slide-id`, 최소 200×100px 표시 영역 |
| `slide-content` | 슬라이드 내부의 실제 제목·본문 |
| `slide-visual` | 슬라이드 내부의 SVG/디코딩된 이미지/비어 있지 않은 2D canvas |
| `slide-source` | 슬라이드 내부의 `data-document-id`, `data-page`; 보이는 파일명·페이지 |

마이크 관찰기는 실제 `getUserMedia`와 `MediaRecorder`에 위임하여 트랙과
바이트 수만 기록합니다. 반환 스트림이나 음성 데이터는 바꾸지 않습니다.
Web Audio/PCM 전송 방식도 live 트랙과 실제 백엔드 바이트 수로 검증할 수 있습니다.

## 결과 파일

실행별 폴더는 `artifacts/e2e/<UTC 시각>-<고유 ID>/`입니다.
`artifacts/e2e/latest.json`이 최신 폴더를 가리킵니다. 사람이 읽는 요약의 시각은 KST입니다.

- `summary.md`, `summary.json`: 전체 단계·상태·시간·종료 코드.
- `media-preflight/`: WAV 캡처 결과, 실제 `captured-fixture.webm`, Chrome 로그.
- `run-01/` 등: `result.json`, 실행 중 `result.partial.json`, `events.jsonl`.
- `browser-console.jsonl`: 콘솔 메시지와 브라우저 JS 오류.
- `api-errors.jsonl`: HTTP 오류, API 요청 연결 실패, WebSocket 핸드셰이크·프레임·명시적 error 메시지; 오류가 없으면 빈 파일.
- `frontend.log`, `backend.log`, `chrome.log`: 프로세스 출력.
- 실패 단계별 PNG와 HTML, 생성 성공 시 `generated-slide.png`.

기동 대기 중 예상되는 헬스체크 재시도는 `events.jsonl`에 별도로 기록합니다.
예상한 세션 삭제 후 404도 기록하되 실패로 세지 않습니다. 예상하지 않은
콘솔 오류, JS 오류, 요청 실패, HTTP/API 오류는 단계가 완료되었더라도
run을 실패시킵니다. 아티팩트는 실패 후에도 삭제하지 않으며 Git에는 포함하지 않습니다.

오류 기록 자체의 검증은 `python scripts/test_harness.py`로 수행합니다.
실제 Chrome에서 의도적인 진단 콘솔/JS 오류와 HTTP 501을 기록하고,
끊긴 API 연결·실패한 WebSocket 핸드셰이크와 실제 WAV 마이크 스트림
관찰기가 정상 작동하는지 검사합니다.
진단 테스트에서는 자막이나 슬라이드를 생성하지 않습니다.

참고: [Puppeteer의 별도 브라우저 설정](https://pptr.dev/guides/configuration),
[Puppeteer 페이지 이벤트](https://pptr.dev/api/puppeteer.pageevent),
[Chromium의 WAV 입력 스위치](https://chromium.googlesource.com/chromium/src/%2B/4cdbc38ac425f5f66467c1290f11aa0e7e98c6a3%5E%21/),
[Next.js 설치](https://nextjs.org/docs/app/getting-started/installation),
[FastAPI 첫 단계](https://fastapi.tiangolo.com/tutorial/first-steps/).
