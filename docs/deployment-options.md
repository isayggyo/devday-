# 배포 방안 — 2026-10-09

현재 코드를 기준으로 조사한 제안이다. 외부 서비스 생성·과금·공개 배포는 수행하지 않았다.
컨테이너 실행은 아직 검증하지 않았으며, 아래 설정은 실제 배포 전 준비 항목이다.

## 추천: Railway의 컨테이너 서비스 2개 + PostgreSQL + 비공개 Bucket

이 앱에는 Next.js BFF, FastAPI WebSocket, 프로세스 내 생성 작업, LibreOffice, Node와 Chrome을
사용하는 PDF 출력이 있다. 기존 구조를 유지하려면 상시 컨테이너가 가장 적은 변경으로 맞는다.
이는 코드 의존성과 플랫폼 문서를 비교한 판단이다.

| 구성 | 역할 | 필요한 연결 |
|---|---|---|
| Next.js 서비스 | Octi UI·파일/API 프록시 | 백엔드 내부 주소, 공개 HTTPS 주소 |
| FastAPI Docker 서비스 | JSON 입력·STT·Q&A·최종 슬라이드·PDF | PostgreSQL·Bucket·OpenAI, 공개 WSS 주소 |
| PostgreSQL 서비스 | 세션·전사·질문·Evidence·생성 결과 | 백엔드만 접근 |
| 비공개 S3 호환 Bucket | 자료·음성·업로드 JSON 원본 | 서버의 S3 자격 증명만 사용 |

Railway는 [Dockerfile 배포](https://docs.railway.com/builds/dockerfiles),
[PostgreSQL 서비스](https://docs.railway.com/databases/postgresql),
[WebSocket 연결](https://docs.railway.com/networking/public-networking/specs-and-limits),
[비공개 S3 호환 Bucket](https://docs.railway.com/storage-buckets)을 제공한다.
WebSocket은 일반 HTTP 요청의 시간/유휴 제한에서 제외된다. 재배포·애플리케이션 종료와
네트워크 끊김에 대비한 기존 재연결 처리는 계속 필요하다.

## 실제 배포 전에 필요한 코드/이미지 준비

1. **운영 인증 연결.** 현재 `backend/auth.py`는 개발 사용자 헤더만 처리하고 JWT 모드에서는
   401을 반환한다. `APP_ENV=production`에서 개발 인증을 금지하므로 환경 변수만 바꾸면
   로그인되지 않는다. 검증된 로그인 토큰에서 사용자 ID를 구하는 처리가 먼저 필요하다.
   공개 API가 브라우저의 `X-Dev-User-Id` 값을 신뢰하게 배포하면 안 된다.
2. 백엔드 Docker 이미지에 Python 의존성, Node 22.12 이상, npm 의존성, Linux용 LibreOffice,
   Puppeteer와 호환되는 Linux Chrome, 한글 폰트를 포함한다. PDF 출력 스크립트가
   `frontend/lib/slides.ts`와 `e2e/core.mjs`도 가져오므로 백엔드 폴더만 복사하면 부족하다.
   로컬 `.env`, API 키 파일, DB 데이터, 로그, `.tools`를 이미지에 복사하지 않는다.
3. `LIBREOFFICE_PATH`와 `E2E_CHROME`을 Linux 실행 파일 경로로 지정한다. Windows의
   `soffice.com`/`chrome.exe`를 그대로 사용할 수 없다. 한글 PDF를 위해 CJK 폰트를 설치한다.
4. Railway의 새 Bucket은 virtual-hosted URL 방식을 사용한다. 현재 `backend/storage.py`는
   path 방식이 고정되어 있어 배포 전에 addressing style을 설정으로 선택하도록 바꿔야 한다.
   [Bucket URL 규격](https://docs.railway.com/storage-buckets#url-style)을 해당 Bucket의 Credentials와 확인한다.
5. 마이그레이션은 백엔드 실행 전 별도 명령 `python -m backend.migrate`로 적용한다.
   Railway의 DB URL은 SQLAlchemy/psycopg에 맞게 `postgresql+psycopg://` 형식을 사용한다.
6. 초기 데모는 Uvicorn worker 1개와 백엔드 replica 1개로 운영한다. 현재 작업 풀·타이머는
   프로세스 메모리 안에 있고 재시작 자동 복구 큐가 없다. 발표 중 배포 변경을 피하고,
   중단된 생성은 기존 재시도 UI로 복구한다. 여러 worker/replica 운영은 별도 검증이 필요하다.

## 환경 변수와 시작 명령

| 위치 | 설정 |
|---|---|
| 프론트 빌드/실행 | `API_BASE_URL` = 백엔드 내부 HTTP 주소, `NEXT_PUBLIC_BACKEND_URL` = 백엔드 공개 HTTPS 주소 |
| 백엔드 | `DATABASE_URL`, `OPENAI_API_KEY`, `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION`, `S3_BUCKET` |
| 백엔드 | `FRONTEND_ORIGIN` = 공개 프론트 HTTPS 주소, `E2E_MODE=false`, 운영 인증 구현 후 `APP_ENV=production` |
| 백엔드 이미지 | `LIBREOFFICE_PATH`, `E2E_CHROME` = 설치한 Linux 실행 파일 경로 |

`NEXT_PUBLIC_BACKEND_URL`은 브라우저 WebSocket 주소에도 쓰이며 빌드 시 반영한다.
브라우저에 내부 주소나 `127.0.0.1`을 넣지 않는다. OpenAI/DB/S3 비밀 값은 백엔드에만 둔다.

Linux 컨테이너의 프론트 빌드/실행 예:

```sh
npm ci
node node_modules/next/dist/bin/next build frontend --webpack
node node_modules/next/dist/bin/next start frontend --hostname 0.0.0.0 --port "$PORT"
```

백엔드 실행 예:

```sh
python -m uvicorn backend.app:app --host 0.0.0.0 --port "$PORT" --workers 1
```

계정에서 프로젝트를 생성하고 DB/Bucket을 연결한 뒤, 두 서비스에 환경 변수·도메인을
지정한다. `/health`와 `/api/backend-health`, JSON/PDF 업로드, WSS 전사, Q&A·최종 슬라이드·
PDF 출력, 세션 삭제를 실제 배포 환경에서 확인한 다음 공유한다.

## 대안 비교

| 방안 | 이 앱에 대한 판단 |
|---|---|
| Render 유료 Web Service + Postgres + 외부 S3/R2 | Docker와 WebSocket을 지원해 유사하게 배포 가능. 저장소는 별도 연결. [Docker](https://render.com/docs/docker), [WebSocket](https://render.com/docs/websocket) |
| Vercel 프론트 + Railway 백엔드 | 가능하지만 현재 Next BFF를 통과하는 PDF 30MB 업로드 경로를 바꿔야 함. Functions의 4.5MB 요청 제한을 피하려면 직접 백엔드/서명 업로드 필요. [Functions 제한](https://vercel.com/docs/functions/limitations) |
| 단일 VPS의 Docker Compose | 현재 개발 구조와 가깝지만 HTTPS·DB/파일 백업·서버 운영을 직접 맡아야 함. 팀에 운영 경험이 있으면 대안 |

Vercel은 현재 [WebSocket을 지원](https://vercel.com/docs/functions/websockets)하므로
“WebSocket 미지원”을 제외 이유로 쓰지 않는다. 이 앱에서는 대용량 BFF 업로드와
네이티브 실행 파일, 프로세스 내 비동기 작업 유지가 주요 고려점이다.
Render 무료 서비스는 [15분 유휴 시 정지 및 시작 지연](https://render.com/docs/free)이 있어
해커톤 발표용 상시 실행 환경으로는 우선 추천하지 않는다.

비용은 Next/FastAPI/DB의 실제 CPU·메모리·전송량과 OpenAI 호출량에 따라 달라진다.
배포 계정·예산·리전이 정해지면 그 조건으로 견적과 최종 서비스 크기를 결정한다.
