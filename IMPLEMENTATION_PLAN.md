# Stock Office — 제품 및 구현 계획

**버전:** 1.0 · **작성:** 2026-10-16 · **상태:** 계획/기술 검증 전

## 1. 제품 목표
미국·한국 주식을 대상으로 AI 투자회사(Investment Committee)가 시장·기업·뉴스를 분석하고 Bull/Bear 토론, 리스크 검토, 최종 의사결정을 수행한다. 실제 Agent 이벤트를 애니메이션으로 보여주고 결과를 저장·재생하며, 별도 규칙 기반 모의투자 엔진에서 성과를 평가한다. **실제 수익이 보장되지 않으며 MVP에는 실주문 기능이 없다.**

## 2. 고정된 결정과 범위
- 프로젝트 루트 `stock-office/`, 제품명 Stock Office (가칭).
- 미국(US:NASDAQ:NVDA)과 한국(KR:KRX:005930) 시장 동시 지원. 종목 식별자 `COUNTRY:EXCHANGE:SYMBOL`.
- TradingAgents를 핵심 Agent 프레임워크로 사용. **구현 시작 시 릴리스/커밋 고정**. 코어 수정 최소화하고 어댑터에서 확장.
- 프론트엔드 React, TypeScript, Vite, React Flow(@xyflow/react), Motion, ECharts. 백엔드 Python FastAPI, 별도 Worker, PostgreSQL, SSE.
- 개인 운영용 데스크톱 웹. 초기에는 사용자/권한, 공개 SaaS, 결제, 실거래 제외.
- 분석 결과는 매수·매도·보유/판단 보류의 제안이며, 모의주문은 결정론적 Risk Policy를 통과해야 한다.
- 실계좌·증권사 주문 키 사용 금지. 기존 코드의 자동주문 경로는 **추출하지 않는다**.

## 3. 화면 명세
| 경로 | 주요 기능 | 완료 조건 |
|---|---|---|
| `/` | 총 가상 자산, 수익률, 진행중 분석, 최근 결정 | 현금+주식 평가금 합계 일치 |
| `/committee` | 종목 검색·위원회 소집, 병렬 Agent 노드, Bull/Bear 토론, 시간순 Activity Feed | 실제 이벤트에 의해 노드가 변화하고 복구·재생됨 |
| `/research/:runId` | 분석별 보고서, 인용 근거, 데이터 공개 시각, 반대 근거, 위험 검토 | 근거 부족 시 `REVIEW`로 표시 |
| `/portfolio` | KRW/USD 현금, 보유·미체결, 거래원장, P&L, 기준지수 | 중복 체결 0, 통화별 정합성 |
| `/history` | 실행 검색, 애니메이션 리플레이, 전략별 비교 A/B/C/D | 동일 조건의 실험만 나란히 비교 |
| `/settings` | 데이터 공급자 건강 상태, 투자 정책, 모델 프로필 | API 키는 서버에만 저장 |

애니메이션 상태는 `PENDING/RUNNING/COMPLETED/FAILED/SKIPPED/BLOCKED`. 장식용 가짜 실행 이벤트 사용 금지. reduced-motion 지원. 병렬 수행 표시. SSE 재연결에서 `Last-Event-ID` 또는 시퀀스 기반 catch-up 제공.

## 4. Agent 흐름과 오픈소스
- TradingAgents: https://github.com/TauricResearch/TradingAgents — 시장/재무/뉴스/감성 애널리스트 → Bull/Bear → Research Manager → Trader → Risk 논쟁 → Portfolio Manager.
- TradingAgents의 `TradingAgentsGraph`, `graph/setup.py`, `graph/propagation.py`를 어댑터 통합 지점으로 검토. 프레임워크 버전마다 실제 상태·신호 계약 재확인.
- Microsoft Qlib: https://github.com/microsoft/qlib — 후속 퀀트 평가 연구 참고.
- vectorbt: https://github.com/polakowo/vectorbt — 전략 백테스트 후보(라이선스와 구현 적합성 확인 후 적용).
- FinRL: https://github.com/AI4Finance-Foundation/FinRL — 추후 강화학습 실험 참고. MVP 통합 불필요.
- 프레임워크의 기본 분석 성공이 곧 투자 전략의 우수함을 의미하지 않음.

## 5. 기존 코드 재사용: 읽기 전용 소스
- https://github.com/eourm20/quant-trading/tree/main
  - `worker/indicators.py`: 40+ 지표 계산(단위·결측·가격 정밀도·시계열 정렬 테스트 후 추출).
  - `worker/monitor.py`: 29개 신호 조건 평가(`KiwoomClient`, DB, 주문 호출과 분리).
  - `worker/clients/*`: 한국 시세·DART·뉴스 참고, 신규 `MarketDataProvider` 인터페이스로 감싸기.
  - `data/db.py`: legacy 데이터 구조 참고, 기존 SQLite 직접 운영 DB로 사용하지 않기.
- https://github.com/eourm20/quant-trading/tree/feature/agent-mode
  - Research/Judgment Agent 및 6개 툴셋: 역할 분리와 오류 처리 설계 참고.
  - FAISS/SQLite RAG, `adaptive_policy.py`, reflection: **비활성 실험군**으로 보류(성과 부진, 데이터 누수·과적합 검토).
  - 실주문/자동주문 경로 절대 연결 금지.
- https://github.com/eourm20/stock-coach
  - `backend/app/services/news/aggregator.py`: DART/Naver/KIND/RSS 뉴스 수집 참조.
  - `backend/app/services/quant_bridge.py`: 기존 DB read-only 수집 패턴 참고. 파일에 쓰기 연결 함수도 존재하므로 해당 부분은 사용 금지.
  - React/FastAPI/성과 평가 UI 레퍼런스. 화면은 새 제품 맥락으로 다시 디자인.

## 6. 기존 투자 성과 해석 주의
기록상 Agent 모드 약 1개월 운영에서 전체 수익 발생하지 않음. 과거 신호 267건 3일 방향 적중률 약 71%, 평균 +4.2%; 모의 거래 32건 승률 54.8%, 거래당 평균 +0.33%라는 **서로 다른 모집단의 단기 평가 수치**가 존재. 포트폴리오 수익률 또는 일반화된 실적처럼 사용 금지. 수수료·슬리피지·실행 가격·중복 신호·시장 환경을 검증하기 전에는 성능 주장하지 않는다.

## 7. 데이터 모델 (PostgreSQL)
- `instruments(id, market, exchange, symbol, currency, provider_symbol)`
- `data_snapshots(id, instrument_id, source, observed_at, available_at, ingested_at, payload_hash, payload)`
- `analysis_runs(id, instrument_id, requested_at, as_of, status, engine_version, config_hash, error_code)`
- `run_data_sources(run_id, snapshot_id)`
- `agent_events(id, run_id, seq, type, agent_id, occurred_at, payload)` UNIQUE(run_id,seq)
- `agent_outputs(id, run_id, agent_id, role, status, summary, structured_output, warnings)`
- `decisions(id, run_id, action, confidence, rationale, counterarguments, risk_flags, created_at)`
- `paper_accounts(id, base_currency, initial_equity)`; `cash_balances(account_id,currency,balance)`; `cash_ledger(...)`
- `paper_orders(id, account_id, decision_id, idempotency_key, status, side, quantity, limit_price)` UNIQUE(idempotency_key)
- `paper_fills(id, order_id, executed_at, price, quantity, fee, tax, currency)`
- `positions(account_id,instrument_id,quantity,avg_cost)`; `portfolio_snapshots(account_id,valued_at,nav_krw,fx_snapshot_id)`
- `strategy_evaluations(id, strategy_id, dataset_version, window_start, window_end, benchmark, costs, metrics)`

모든 타임스탬프 UTC 저장, 거래소 로컬 시간은 표시 시 변환. 거래 주문·현금·포지션은 한 트랜잭션. 과거 분석은 `available_at <= as_of` 강제. 기존 계좌 잔고 파일은 절대 이관하지 않는다.

## 8. API 및 주요 타입
- `GET /api/v1/instruments?q=&market=`
- `POST /api/v1/analysis-runs` → `{run_id,status:'QUEUED'}`
- `GET /api/v1/analysis-runs/{id}` / `.../events`(SSE) / `.../outputs` / `.../decision`
- `GET /api/v1/analysis-runs` / `GET /api/v1/portfolio` / `GET /api/v1/portfolio/performance`
- `POST /api/v1/paper-orders` / `GET /api/v1/paper-orders` / `GET|PATCH /api/v1/settings`

Agent 결과 공통 구조: `{run_id,agent_id,role,status,started_at,completed_at,summary,findings:[{claim,polarity,evidence_snapshot_ids}],structured_output,warnings}`.
Decision: `{run_id,action:'BUY'|'SELL'|'HOLD'|'REVIEW',proposed_weight_pct,confidence,rationale,counterarguments,risk_flags,evidence_snapshot_ids,model_version}`. **confidence는 모델 자기평가이지 확률 아님**.
Event: `{event_id,run_id,seq,type,agent_id,occurred_at,payload}`. 엔진 내부 비공개 추론, 키 및 원문 프롬프트 저장·노출 금지. 실패/결측은 `REVIEW` 또는 거래 차단.

## 9. Sprint/Phase 계획
### Sprint 0 — 기술 검증 / 첫 수직 슬라이스
1. 루트 저장소 및 Python/Frontend 최소 개발 환경. 의존성 lock, `env.example`, 린트·테스트.
2. TradingAgents 릴리스와 LICENSE, 사용 가능한 public API 및 stream 이벤트 확인. 버전 고정.
3. 미국 `NVDA` 분석: 실제 공급자 시세·뉴스/공시 수집, Agent 실행, 결과 JSON 저장.
4. `TradingAgentsAdapter`가 시작/종료/오류·토론 이벤트 정규화해 JSONL로 저장. 실시간은 SSE 테스트.
5. 한국 `005930` 데이터 매핑 및 지원 범위 검증: DART/KIS 또는 기존 키움 ReadOnly Provider. 국내 재무/뉴스도 스냅샷 정규화.
6. 비용·지연시간·결측·실패·출처·시점 보고. 핵심 결과 2종목 재현 가능한 샘플 스냅샷과 테스트.
**합격:** US/KR 각 1종목 분석 성공, Agent 이벤트 순서·결과 저장/재생, 계좌/주문 연동 없음. 한국 분석 지원 불완전 시 실패 이유와 단계별 차단을 명시하고 차기 스프린트로 넘기기.
### Sprint 1 — 데이터 통합/분석 신뢰성
DataProvider/IndicatorProvider 어댑터, KR·US 시점 정합성, 테스트 3종목씩, API·DB, 큐, 도구별 회귀테스트.
### Sprint 2 — 투자회사 UI
React Flow 에이전트 노드·Activity Feed, 토론·보고서, 리플레이, SSE 재연결, 접근성.
### Sprint 3 — 모의투자
가상 계좌 및 FX, 결정론적 정책, 주문/체결/원장/포지션, 수수료·슬리피지·거래일력, 전략 수익률.
### Sprint 4 — 성과 분석·품질
동일 구간 A vs C 비교, 이후 B/D 독립 검증, 벤치마크, 리스크 지표, point-in-time 및 부하/오류 테스트.

## 10. 보안·실험 규칙
- 기존 브랜치/데이터 수정 금지. 실거래 SDK 주문 메서드 호출 금지. 비밀키는 `.env`/서버 비밀 저장소에서만. `.env`/실제 DB git ignore.
- 기본 설정 `PAPER_ONLY=true`. 주문 모듈에는 외부 거래소 API 네트워크 호출 구현 자체를 두지 않는다.
- 테스트 모의체결은 시장가·휴장·시세 지연·FX 결측 및 수수료를 분리 검증. 호출된 모델/가격/공시 공개시점 기록.
- 신호 적중률·거래 승률·포트폴리오 수익률을 구별. 성과 비교는 동일한 시장/기간/종목/자본/비용에서만 수행.
- 프레임워크나 라이브러리 최신 상태를 실행 시점에 재확인; 검증하지 않은 기능은 명확히 TODO로 남김.

## 11. 포트폴리오 증빙 계획
노션 경험창고에는 완료된 기능만 **실제 구현 성과**로 기록. 현재는 계획 단계. 단계별 구현 동영상/스크린샷(가짜 시세 대신 모의 표시), Agent event JSON 예시, 아키텍처, US/KR 커버리지, 재현 가능한 실험 리포트, 비용/지연시간, 전략별 기준선 결과를 축적한다.

## 12. 완료 정의
- NVDA/005930 + 추가 각 2종목 실제 분석, 시각화, 저장·재생.
- 근거 링크/가용시각과 오류 처리 검증.
- PAPER 주문만 실행, 위험 정책 및 idempotency 테스트 통과.
- KRW 기준 NAV 계산과 USD 원장·FX 평가 일치.
- 종목/시장별 보고서 및 전략 성과 비교.
- 테스트/실행 방법/제한사항 문서화, 배포용 비밀키 노출 없음.

## 13. 진행 현황 / 변경 기록
### 2026-10-16 — Sprint 0 구현 (게이트 미통과: 실제 LLM 분석 차단)
상세: `docs/sprint-0-report.md` · 증빙 초안: `docs/portfolio-evidence.md`
- [x] 1. Python(uv, `backend/.venv`, `uv.lock`)·Frontend(Vite/React/TS, `package-lock.json`) 최소 환경, `.env.example`, ruff/mypy strict/pytest/vitest
- [x] 2. TradingAgents v0.6.0 @ `1394a3f`(Apache-2.0) 검증·고정, 노드명/등급 계약 테스트
- [x] 3. NVDA 실제 분석 — 2026-10-16 run `641430f80ae149b9` COMPLETED (economy 프로필, 163초, 약 $0.04). 상세: sprint-0-report §10
- [x] 4. `TradingAgentsAdapter` 이벤트 정규화 → JSONL 저장, SSE 재생/재접속(Last-Event-ID) 테스트
- [~] 5. 005930 매핑 + Yahoo 시세 + **OpenDART live 검증 완료**(공시 15건). 005930 실제 LLM 분석은 미실행. KIS/키움 read-only 미구현
- [~] 6. 결측·실패·출처·시점 보고 구현. 비용/실분석 지연시간 **미측정**
- 계획 대비 편차: Sprint 0 저장소는 PostgreSQL 대신 파일(JSON/JSONL) — Sprint 1에서 이관. TradingAgents 메모리 로그/리플렉션은 run별 격리로 비활성화.
### 2026-10-16 — 비용 프로필 / 유료 테스트 가드
- `STOCK_OFFICE_TA_COST_PROFILE=economy|standard` 추가. economy(개발·테스트 기본)는 분석가 도구 반복 상한 20→6, 기사 수 20→10 / 10→5만 축소. deep 모델·추론 강도·max_tokens는 유지. 프로필과 `TRADINGAGENTS_*` 환경변수 오버라이드를 `config_hash`·`model_version`에 기록.
- 합격 판정·성과 평가 실행은 `standard`로 한다. 1회 비교는 토큰 절감량만 측정하며 품질 동등성 근거가 아님.
- 실제 LLM live 테스트는 키 + `STOCK_OFFICE_ALLOW_PAID_TESTS=1`일 때만 실행되어 `-m live`만으로는 과금되지 않음.
