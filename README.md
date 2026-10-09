# DevDay Seoul 2026

2026년 10월 9일 DevDay Community Hackathon Seoul 작업 저장소입니다.

- 저장소: https://github.com/isayggyo/devday-
- 브랜치: `main`
- 로그 수집 시작: **2026-10-09 10:28:01 KST**
- 작업 경과: [docs/work-log.md](docs/work-log.md)

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
