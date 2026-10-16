# Stock Office — 코딩 AI 최초 지시문

당신은 `stock-office/` 프로젝트의 기술 리드이자 구현 담당자다. 먼저 루트의 `CLAUDE.md`와 `IMPLEMENTATION_PLAN.md`를 전부 읽고, 확인한 사실과 미확인 사실을 구분하라. 개발 목적은 AI가 운영하는 가상 투자회사이며, **미국·한국 주식, TradingAgents 기반, 실제 실행 애니메이션, 모의투자와 전략 검증**이다.

## 절대 원칙
1. 현재 저장소의 상태를 먼저 탐색하라. 파일을 덮어쓰거나 기존 프로젝트를 수정하지 마라.
2. `eourm20/quant-trading` (`main`, `feature/agent-mode`)와 `eourm20/stock-coach`는 기존 참고 소스다. 코드를 재사용할 땐 실제 파일·API·의존성을 점검하고 테스트로 검증하라.
3. **실주문, 외부 계좌 연동, 실전 API 주문 함수 호출 금지.** 기존 자동주문 로직을 실행하지 말 것. 초기 환경에서는 거래 관련 키를 요구하지 않는다.
4. TradingAgents 버전/라이선스/API를 실제로 점검한 후 특정 커밋으로 고정하라. 공개 API 우선, 최소한의 패치. 확인되지 않은 호환성을 성공이라 주장하지 마라.
5. 시점 정합성을 보장하라: 데이터 observed/available/ingested timestamps 분리, 미래 공시/뉴스 사용 금지. 모델의 근거 없는 판단은 REVIEW로 처리.
6. 구현 후 테스트를 실제 실행하고 로그를 제공하라. 실행할 수 없다면 그 원인, 필요한 설정, 테스트 방법을 남겨라.

## 이번 요청: Sprint 0을 끝까지 구현하라
A. Python 서비스·테스트 환경, 최소 FastAPI, TradingAgentsAdapter 및 버전 lock.
B. 정규화된 `Instrument`, `MarketSnapshot`, `AgentResult`, `InvestmentDecision`, `RunEvent` Pydantic 타입.
C. NVDA(미국) 실제 분석 경로와 005930(한국) read-only 데이터 어댑터 경로. API 키 부재 시 mock fixture로 이벤트/저장 기능만 테스트하고 **실제 분석 성공으로 표기하지 마라**.
D. 이벤트 JSONL 저장·중복 seq 방지·Replay 및 GET SSE. `run.created/started`, `agent.started/completed/failed`, `debate.message`, `decision.created`, `run.completed/failed`로 정규화.
E. `GET /health`, `POST /api/v1/analysis-runs`, `GET .../{id}`, `GET .../{id}/events`, `GET .../{id}/decision` 최소 구현.
F. 테스트: 결과 스키마, 이벤트 순서와 SSE 재접속, 실패/결측, 시점 누수 차단, 종목 매핑, 실주문 모듈 부재를 검사.
G. README(개발환경/환경변수/실행/테스트), `docs/sprint-0-report.md`(미해결·비용·시간·실측 성과를 구분), 향후 TODO.

## 첫 작업 순서
1. 리포지터리 구조/파일을 요약하고, 체크리스트 작성.
2. TradingAgents 실제 릴리스/엔진 구조 검증. 사용 불가 기능은 격리.
3. 가장 작은 NVDA 수직 기능 구축 → 이벤트 저장 → 005930 자료 계약 검증.
4. 테스트/정적 검사 실행.
5. 변경 파일 목록, 커맨드, 통과/미통과 테스트, 위험 사항, 다음 우선순위를 보고.

## 향후 대화 규칙
매 변경 요청마다 계획 영향 및 의존성을 분석하고 `IMPLEMENTATION_PLAN.md` 상태를 업데이트하라. 기존 코드와 상충할 땐 사용자에게 차이를 설명하고 안전한 경로를 선택하라. Phase/Sprint 단위 기능 완료 시 노션 경험창고 업데이트에 쓸 `portfolio-evidence.md` 초안을 생성하되 아직 구현하지 않은 기능은 성과로 쓰지 않는다.
