# Stock Office — 제품 및 구현 계획

**버전:** 1.1 · **작성:** 2026-10-16 · **상태:** Sprint 0 완료(합격) · 게임형 오피스 UI 설계 확정, 구현 전 (Sprint 2A~2C)

## 1. 제품 목표
미국·한국 주식을 대상으로 AI 투자회사(Investment Committee)가 시장·기업·뉴스를 분석하고 Bull/Bear 토론, 리스크 검토, 최종 의사결정을 수행한다. 실제 Agent 이벤트를 **2.5D 아이소메트릭 픽셀아트 오피스**에서 AI 직원들의 행동(이동·착석·작업·토론·보고)으로 보여주고 결과를 저장·재생하며, 별도 규칙 기반 모의투자 엔진에서 성과를 평가한다. **실제 수익이 보장되지 않으며 MVP에는 실주문 기능이 없다.**

## 2. 고정된 결정과 범위
- 프로젝트 루트 `stock-office/`, 제품명 Stock Office (가칭).
- 미국(US:NASDAQ:NVDA)과 한국(KR:KRX:005930) 시장 동시 지원. 종목 식별자 `COUNTRY:EXCHANGE:SYMBOL`.
- TradingAgents를 핵심 Agent 프레임워크로 사용. **구현 시작 시 릴리스/커밋 고정**. 코어 수정 최소화하고 어댑터에서 확장.
- 프론트엔드 Next.js, React, TypeScript, Phaser 3(Office Mode), Tiled Map Editor(맵), Tailwind CSS + shadcn/ui(UI 패널), React Flow(@xyflow/react, Analysis Mode), ECharts(금융 차트). 백엔드 Python FastAPI, 별도 Worker, PostgreSQL, SSE. Multi-Agent는 TradingAgents(LangGraph).
  - 2026-10-16 변경: 기존 Vite + React Flow 중심 화면 → 게임형 오피스가 메인. Sprint 0의 Vite 개발 콘솔은 Sprint 2A에서 Next.js로 이관한다.
- 개인 운영용 데스크톱 웹. 초기에는 사용자/권한, 공개 SaaS, 결제, 실거래 제외.
- 분석 결과는 매수·매도·보유/판단 보류의 제안이며, 모의주문은 결정론적 Risk Policy를 통과해야 한다.
- 실계좌·증권사 주문 키 사용 금지. 기존 코드의 자동주문 경로는 **추출하지 않는다**.

## 3. 화면 명세
| 경로 | 주요 기능 | 완료 조건 |
|---|---|---|
| `/` **Office Mode (메인)** | 픽셀아트 사무실, AI 직원 실시간 행동, Agent 클릭 시 상세 패널, Activity Feed, Bull/Bear 말풍선, 최종 투자 결정, 종목 선택·분석 시작, 상단 HUD(가상 자산·진행중 분석) | 캐릭터 상태가 실제 이벤트에서만 바뀌고, 같은 이벤트 로그는 같은 상태로 재생됨. DEMO 재생은 DEMO 표시 |
| `/analysis/:runId` **Analysis Mode** | React Flow Agent 실행 그래프, Agent별 보고서, 인용 근거·데이터 공개 시각, 토론 기록, 최종 판단·위험 검토 | 근거 부족 시 `REVIEW`로 표시 |
| `/characters` | 캐릭터 업로드, 미리보기, Agent 할당, 기본/사용자 캐릭터 전환 | 할당 변경이 분석·이벤트에 영향 없음, 매핑 영속 저장 |
| `/portfolio` **Portfolio Mode** | KRW/USD 현금, 보유·미체결, 주문·체결 기록, P&L, 벤치마크 비교 | 중복 체결 0, 통화별 정합성, 현금+주식 평가금 합계 일치 |
| `/history` | 실행 검색, 애니메이션 리플레이, 전략별 비교 A/B/C/D | 동일 조건의 실험만 나란히 비교 |
| `/settings` | 데이터 공급자 건강 상태, 투자 정책, 모델 프로필 | API 키는 서버에만 저장 |

Agent 상태는 `PENDING/RUNNING/COMPLETED/FAILED/SKIPPED/BLOCKED`. 장식용 가짜 실행 이벤트 사용 금지(걷기·대기 같은 연출은 허용하되 진행 상태를 암시하지 않음, §3a). reduced-motion 지원. 병렬 수행 표시. SSE 재연결에서 `Last-Event-ID` 또는 시퀀스 기반 catch-up 제공.

## 3a. 게임형 오피스와 사용자 캐릭터 시스템 (2026-10-16 확정)
**공간 구성**
| 공간 | 상주 Agent |
|---|---|
| Analyst Office | Market, News, Fundamentals, Sentiment Analyst |
| Research Room | Bull, Bear, Research Manager |
| Trading Desk | Trader |
| Risk & Executive Office | Risk Team(Aggressive/Conservative/Neutral), Portfolio Manager |

2.5D 아이소메트릭 시점, 카메라 확대·축소·이동. 직원이 책상과 회의실 사이를 이동하고, 착석해 컴퓨터를 쓰고, 회의실에서 토론하고, 보고서를 전달한다. 데이터 수집(`data_collector`)과 Memory Log 같은 시스템 단계는 사무실 오브젝트(서버 랙·파일 캐비닛 등)로 표현한다.

**구조 (실행과 연출의 분리)**
`SSE/재생 이벤트 → Event Adapter → Character State Machine → Phaser Scene`
- Event Adapter: 정규화 이벤트를 캐릭터 명령(`goTo`, `work`, `talk`, `report`, `celebrate`, `fail`)으로 변환. 순수 함수이며 단위 테스트 대상.
- Character State Machine: 캐릭터별 상태(`idle/walk/work/talk/report/done/failed`)는 이벤트 seq에만 의존 → 같은 로그는 같은 상태로 결정론적 재생.
- Phaser Scene: 상태를 그릴 뿐 API 호출·투자 판단 없음. 연출 큐가 밀리면 이동 연출을 생략해 따라잡고, 이벤트는 버리지 않는다. 애니메이션이 백엔드 실행을 지연시키지 않는다(백엔드는 연출과 무관하게 진행).

**이벤트 → 캐릭터 행동**
| 이벤트 | 행동 | 상태 |
|---|---|---|
| `agent.started` | 작업 위치로 이동 후 업무 시작 | 구현됨 (Sprint 0) |
| `agent.completed` | 작업 완료·보고(다음 단계 담당자에게 문서 전달) | 구현됨 |
| `agent.failed` | 실패 표시(머리 위 경고) | 구현됨 |
| `debate.message` | Bull/Bear·리스크 토론, 말풍선(정제된 발언 요약) | 구현됨 |
| `decision.created` | Portfolio Manager 최종 결정 발표 | 구현됨 |
| `tool.called` | 데이터 조회·문서 확인 애니메이션 | **신규 (Sprint 2B)**: 도구명·데이터 공급자만 공개, 인자·원문 결과·프롬프트는 비공개 |
| `risk.rejected` | 위험 검토에서 제안 거절 | **신규 (Sprint 3)**: 결정론적 Risk Policy가 모의주문 제안을 거부할 때만 발생 (LLM 토론 결과가 아님) |
| `order.filled` | 모의 주문 체결 연출 | **신규 (Sprint 3)**: PAPER 체결에서만 발생 |

**사용자 제작 캐릭터 요구사항**
1. Agent 역할과 캐릭터 외형 분리: `agent_id → character_id → asset_id` 매핑.
2. 투명 PNG, Sprite Sheet + 애니메이션 메타데이터 JSON 지원.
3. 우선 동작 `idle`, `walk`, `work`, `talk`. 방향 `down/up/left/right`(앞·뒤·좌·우) 4방향.
4. 정적 PNG 1장만 등록해도 기본 대기(idle) 상태로 사용(누락 동작·방향은 idle 또는 기본 캐릭터로 대체).
5. 업로드·미리보기·Agent 할당 UI, 기본 캐릭터 ↔ 사용자 캐릭터 전환.
6. 매핑은 서버에 영속 저장(PostgreSQL). 이미지 교체가 분석·이벤트 로직에 영향 없음.
7. 기본 프레임 64×64px, 설정으로 변경 가능(메타데이터에 `frame_width/frame_height` 명시).
8. 업로드 보안: PNG·JSON만 허용(SVG/HTML 금지), 파일 크기·프레임 수 상한, 메타데이터 스키마 검증, 업로드 파일은 정적 비실행 자원으로만 제공.
9. 기본 캐릭터·타일 아트는 자체 제작 또는 CC0 등 라이선스 확인된 자산만 사용하고 출처를 기록.

**캐릭터 제작 방침 (2026-10-16)**
- 현재 사용자 제작 캐릭터가 없으므로, 초기 개발에서는 **임시 픽셀아트 캐릭터(Placeholder)**를 역할별로 배치한다.
- 실제 캐릭터 리소스가 없으면 **라이선스가 확인된 임시 게임 에셋**(CC0 등)을 쓰고, 출처·라이선스를 레지스트리에 기록한다.
- 캐릭터 리소스는 별도 **Character Registry**에서 관리한다. 2A~2B에서는 저장소 안 파일 기반(`frontend/public/characters/registry.json` + 에셋 폴더)으로 시작하고, 2C에서 서버 저장(§7 테이블)으로 옮긴다. 두 방식은 같은 스키마(`agent_id → character_id → asset_id`, 메타데이터 JSON)를 쓴다.
- 이후 사용자 제작 스프라이트 시트를 추가하면, 레지스트리 항목만 바꿔 기존 캐릭터를 교체할 수 있어야 한다.
- 캐릭터 교체 시 TradingAgents 분석 로직과 이벤트 시스템은 변경하지 않는다.
- 캐릭터 에디터·업로드 UI는 서두르지 않는다. 지금은 **개발용 에셋 교체 구조**만 준비하고, 사용자 제작 캐릭터 업로드·관리 기능은 **Sprint 2C**에서 구현한다.

메타데이터 예시:
```json
{"frame_width": 64, "frame_height": 64,
 "animations": {"walk": {"down": {"row": 0, "frames": 4, "fps": 8}, "up": {"row": 1, "frames": 4, "fps": 8}},
                "idle": {"down": {"row": 4, "frames": 2, "fps": 2}}}}
```

**접근성**: reduced-motion에서는 걷기 대신 자리 전환, 주변 연출 없음. 캔버스와 동일한 정보를 Activity Feed·Agent 패널 텍스트로 제공.

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
- `character_assets(id, kind:'static_png'|'sprite_sheet', storage_path, sha256, width, height, frame_width, frame_height, metadata, license, uploaded_at)`
- `characters(id, name, is_default, asset_id)`; `agent_character_assignments(agent_id PRIMARY KEY, character_id, updated_at)`

모든 타임스탬프 UTC 저장, 거래소 로컬 시간은 표시 시 변환. 거래 주문·현금·포지션은 한 트랜잭션. 과거 분석은 `available_at <= as_of` 강제. 기존 계좌 잔고 파일은 절대 이관하지 않는다.

## 8. API 및 주요 타입
- `GET /api/v1/instruments?q=&market=`
- `POST /api/v1/analysis-runs` → `{run_id,status:'QUEUED'}`
- `GET /api/v1/analysis-runs/{id}` / `.../events`(SSE) / `.../outputs` / `.../decision`
- `GET /api/v1/analysis-runs` / `GET /api/v1/portfolio` / `GET /api/v1/portfolio/performance`
- `POST /api/v1/paper-orders` / `GET /api/v1/paper-orders` / `GET|PATCH /api/v1/settings`
- `POST /api/v1/character-assets`(multipart: PNG + 메타데이터 JSON) / `GET /api/v1/characters` / `PUT /api/v1/agents/{agent_id}/character` / `DELETE /api/v1/agents/{agent_id}/character`(기본 캐릭터로 복귀)

Agent 결과 공통 구조: `{run_id,agent_id,role,status,started_at,completed_at,summary,findings:[{claim,polarity,evidence_snapshot_ids}],structured_output,warnings}`.
Decision: `{run_id,action:'BUY'|'SELL'|'HOLD'|'REVIEW',proposed_weight_pct,confidence,rationale,counterarguments,risk_flags,evidence_snapshot_ids,model_version}`. **confidence는 모델 자기평가이지 확률 아님**.
Event: `{event_id,run_id,seq,type,agent_id,occurred_at,payload}`. 타입: `run.created/started/completed/failed`, `agent.started/completed/failed`, `debate.message`, `decision.created` (구현됨) + `tool.called`(2B), `risk.rejected`·`order.filled`(Sprint 3). 엔진 내부 비공개 추론, 키 및 원문 프롬프트 저장·노출 금지. 실패/결측은 `REVIEW` 또는 거래 차단.

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
### Sprint 2 — 게임형 투자회사 UI (2A/2B/2C로 분리)
- **2A — Phaser 오피스·캐릭터 (첫 게임형 Vertical Slice):** Next.js 이관, Phaser 3 + Tiled 사무실 1개, 캐릭터 4명(라이선스 확인된 Placeholder 픽셀아트, 파일 기반 Character Registry로 교체 가능), 이동·착석·작업·토론 애니메이션, 카메라 줌·이동, Event Adapter·Character State Machine(단위 테스트), 저장된 이벤트 재생(DEMO 엔진 실행 + Sprint 0 실제 실행 로그를 재생 소스로 사용, DEMO는 DEMO 표시), reduced-motion.
  **합격:** 같은 이벤트 로그 → 같은 캐릭터 상태(결정론 테스트), 연출이 백엔드에 영향 없음, 데스크톱에서 60fps 근처로 동작.
- **2B — 실제 이벤트 연결:** 실시간 SSE·재접속 catch-up, 전체 Agent(13개)와 4개 공간으로 확장, `tool.called` 이벤트 추가(정제), Agent 클릭 상세 패널, Activity Feed·말풍선·결정 패널, Analysis Mode(React Flow 그래프·보고서).
- **2C — 사용자 캐릭터:** 파일 기반 Character Registry를 서버 저장으로 이관, 업로드·미리보기·할당·기본(Placeholder) 전환, 메타데이터 검증, 영속 저장(PostgreSQL 필요 → Sprint 1 이후), 업로드 보안 테스트.
- **권장 순서:** 2A → 2B → Sprint 1(PostgreSQL·데이터 신뢰성) → 2C → Sprint 3 → Sprint 4. 2A·2B는 DB 없이 현재 파일 저장소로 가능하다.
### Sprint 3 — 모의투자
가상 계좌 및 FX, 결정론적 정책, 주문/체결/원장/포지션, 수수료·슬리피지·거래일력, 전략 수익률. `risk.rejected`·`order.filled` 이벤트와 오피스 연출, Portfolio Mode 화면.
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
### 2026-10-16 — Sprint 0 구현 (합격: US/KR 실제 분석 완료)
상세: `docs/sprint-0-report.md` · 증빙 초안: `docs/portfolio-evidence.md`
- [x] 1. Python(uv, `backend/.venv`, `uv.lock`)·Frontend(Vite/React/TS, `package-lock.json`) 최소 환경, `.env.example`, ruff/mypy strict/pytest/vitest
- [x] 2. TradingAgents v0.6.0 @ `1394a3f`(Apache-2.0) 검증·고정, 노드명/등급 계약 테스트
- [x] 3. NVDA 실제 분석 — 2026-10-16 run `641430f80ae149b9` COMPLETED (economy 프로필, 163초, 약 $0.04). 상세: sprint-0-report §10
- [x] 4. `TradingAgentsAdapter` 이벤트 정규화 → JSONL 저장, SSE 재생/재접속(Last-Event-ID) 테스트
- [x] 5. 005930 매핑 + Yahoo 시세 + OpenDART live 검증 완료. 실제 분석 run `0950497c54eb44b7` COMPLETED(139초, 약 $0.037). KR 뉴스는 DART 공시로 보강. KIS/키움 read-only는 미구현(후속)
- [x] 6. 결측·실패·출처·시점 보고 구현. 실측: NVDA 163초·약 $0.04, 005930 139초·약 $0.037 (economy, sprint-0-report §10–11)
- 계획 대비 편차: Sprint 0 저장소는 PostgreSQL 대신 파일(JSON/JSONL) — Sprint 1에서 이관. TradingAgents 메모리 로그/리플렉션은 run별 격리로 비활성화.
### 2026-10-16 — 비용 프로필 / 유료 테스트 가드
- `STOCK_OFFICE_TA_COST_PROFILE=economy|standard` 추가. economy(개발·테스트 기본)는 분석가 도구 반복 상한 20→6, 기사 수 20→10 / 10→5만 축소. deep 모델·추론 강도·max_tokens는 유지. 프로필과 `TRADINGAGENTS_*` 환경변수 오버라이드를 `config_hash`·`model_version`에 기록.
- 합격 판정·성과 평가 실행은 `standard`로 한다. 1회 비교는 토큰 절감량만 측정하며 품질 동등성 근거가 아님.
- 실제 LLM live 테스트는 키 + `STOCK_OFFICE_ALLOW_PAID_TESTS=1`일 때만 실행되어 `-m live`만으로는 과금되지 않음.
### 2026-10-16 — 프론트엔드 방향 변경: 게임형 오피스 UI·사용자 캐릭터
- 메인 화면을 React Flow 워크플로우에서 **2.5D 아이소메트릭 픽셀아트 오피스(Phaser 3 + Tiled)**로 변경. React Flow는 Analysis Mode로 이동. 스택에 Next.js, Tailwind CSS, shadcn/ui 추가(§2, §3, §3a).
- 사용자 캐릭터 시스템(역할·외형 분리, 업로드·할당, 영속 저장) 요구사항과 데이터 모델·API 추가(§3a, §7, §8).
- 신규 이벤트 `tool.called`(2B), `risk.rejected`·`order.filled`(Sprint 3) 계약 추가. 기존 이벤트 계약은 변경 없음.
- Sprint 2를 2A/2B/2C로 분리하고 권장 순서를 기록. Sprint 0 결과·백엔드는 변경 없음.
- 캐릭터 제작 방침: 초기에는 라이선스 확인된 Placeholder 캐릭터를 Character Registry로 관리하고, 업로드·관리 UI는 2C로 미룬다(§3a).
