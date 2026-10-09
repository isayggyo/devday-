# Octi frontend integration

2026-10-09 KST. 기존 main 이력과 backend/API, 원본 녹음·전사·질문 controller를 유지하며 화면을 이식했다. 원본 프론트는 별도 디렉터리에 그대로 남아 있다.

## 화면

- `/`: 실제 팀원 API를 사용하는 Octi 워크스페이스. 녹음 controller를 탭 전환·홈 이동에서도 마운트 상태로 유지한다. 마이크 준비·녹음·마무리 중 다른 세션 선택 및 신규 생성은 비활성화한다.
- `/landing`: 기존 랜딩 이식 및 Octi 이름 반영.
- `/preview`: 기존 프로토타입의 연출 전체 보존. 화면 상단에 샘플임을 표시한다. 해당 화면의 음성·파일 업로드·답변·세션 삭제는 실제 서버 기능이 아니다.

## 연결 상태

| 기능 | 현재 처리 |
|---|---|
| 세션 생성/조회 | 팀원 기존 API 유지 |
| 실제 마이크 녹음, IndexedDB 원본 백업, 청크 재전송/다운로드 | 기존 AudioController 유지 |
| 실시간 전사, 자막, 전사 재연결 | 기존 TranscriptionController 유지 |
| PDF/PPT/PPTX 업로드·페이지·원본·재시도 | 기존 Materials 유지 |
| 실시간 요약·원문 출처·재시도 | 기존 LiveNotes 유지, 점선 타임라인 추가 |
| 질문 시점 고정 맥락·출처·선택 자료·질문 재시도 | 기존 Questions API 유지 |
| 답변별 비교표/흐름도/개념도/수식 | 기존 VisualExplanation 및 KaTeX 유지 |
| 옥티 떠오름·스퀴시·깜빡임·입·방울 | 실제 홈/질문 빈 화면에 연결 |
| 이해도 선택 | 실제 노트에서 화면 상태만 변경. 서버 저장·다음 학습 자동 유도 미연결 |
| 녹음 일시정지/재개 | 서버 및 controller 미구현. 미리보기 연출 유지 |
| 강의 최종 종료, 전체 요약 슬라이드, 저장 중 로딩, 완료 파티클 | 서버 Step 10 미구현. 미리보기 연출 유지, 실제 화면 완료로 표시하지 않음 |
| 오디오/영상 파일 업로드 | 팀원 API는 강의자료 PDF/PPT만 지원. 미리보기 연출 유지 |
| 세션 이름 변경/삭제 | 일반 사용자 API 미구현. 미리보기 로컬 상태 연출 유지 |
| 구간별 대화 탭 및 이해도별 자동 추가 질문 | 미리보기 유지. 실제 질문은 팀원 서버의 고정 맥락 방식 사용 |

## 검증

- `npx tsc --noEmit -p frontend/tsconfig.json`: PASS.
- `node --experimental-strip-types --test frontend/tests/*.test.ts`: 7/7 PASS.
- `npx next build frontend`: PASS, `/`, `/landing`, `/preview` 빌드 확인.
- `npm run test:harness`: 로컬 서버 제한을 해소한 재실행 11/12 PASS. 마지막 관측 테스트는 Chrome for Testing 미설치로 실행 불가. 새 기능 실패로 간주하거나 통과로 기록하지 않는다.
- 로컬 3001 브라우저에서 홈 캐릭터 및 레이아웃 확인. API는 BACKEND_UNAVAILABLE을 표시함. 이 컴퓨터의 DB/S3/OpenAI 환경을 설정하지 않아 실제 녹음·질문·자료 업로드 E2E는 재실행하지 않음.
- 변경 사항은 로컬이며 GitHub push하지 않음.
