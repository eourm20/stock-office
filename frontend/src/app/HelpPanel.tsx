"use client";

import { useEffect } from "react";

/** "보는 법": how to read the office and what each control does. */
export default function HelpPanel({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="help-title"
           className="max-h-[88vh] w-[min(760px,100%)] overflow-y-auto rounded-2xl border border-[var(--line)] bg-[var(--panel)] p-6 text-[14px] leading-relaxed"
           onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 id="help-title" className="text-lg font-bold">Stock Office 보는 법</h2>
          <button onClick={onClose} className="rounded bg-[var(--line)] px-3 py-1" autoFocus>닫기 (Esc)</button>
        </div>

        <h3 className="mt-2 font-semibold text-[var(--mint)]">이 화면은 무엇인가요?</h3>
        <p>AI 직원들이 한 종목을 두고 회의하는 모습을 보여 줍니다. 분석가가 자료를 조사하고, 강세·약세 연구원이 토론하고,
          리스크 팀이 위험을 따진 뒤, 포트폴리오 매니저가 <b>매수 / 매도 / 보유 / 판단 보류</b> 중 하나를 제안합니다.
          캐릭터가 무엇을 하는지는 실제 AI 실행 기록 그대로이고, 걷는 모습만 연출입니다. <b>실제 주문은 절대 하지 않습니다.</b></p>

        <h3 className="mt-4 font-semibold text-[var(--mint)]">위쪽 버튼</h3>
        <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-2">
          <dt className="font-semibold">자동 모드</dt>
          <dd>처음 들어오면 켜져 있습니다. 진행 중인 회의가 있으면 <b>실시간</b>으로 보여 주고, 없으면 <b>가장 최근 회의 결과</b>를 바로 보여 줍니다.
            15초마다 확인해서 새 회의가 시작되면 알아서 그 회의로 넘어갑니다.</dd>
          <dt className="font-semibold">종목 카드</dt>
          <dd>사무실 위의 카드는 종목별 <b>가장 최근 실제 분석 의견</b>과 언제 나왔는지입니다(DEMO는 제외). 누르면 그 회의를 봅니다.
            ‘● 회의 중’이면 지금 분석이 진행 중이라는 뜻입니다. 카드를 누르면 자동 모드가 꺼지고, ‘자동 모드로’를 누르면 다시 켜집니다.</dd>
          <dt className="font-semibold">기록 보기</dt>
          <dd>지금까지 연 모든 회의 목록입니다. <b>실제 분석</b>은 TradingAgents가 실제 데이터로 분석한 기록이고, <b>DEMO</b>는 화면 시험용 가짜 데이터입니다.</dd>
          <dt className="font-semibold">1× / 4× / 즉시</dt>
          <dd>다시보기 속도입니다. 실제 회의는 2~3분 걸리는데 1×는 그 시간을 줄여서, 4×는 더 빠르게 보여 줍니다. ‘즉시’는 결과만 바로 보여 줍니다.
            발언이 나오면 읽을 시간만큼 잠시 멈춥니다.</dd>
          <dt className="font-semibold">일시정지 / 재생</dt>
          <dd>다시보기를 멈추거나 이어서 봅니다.</dd>
          <dt className="font-semibold">회의 다시보기</dt>
          <dd>보고 있는 회의를 처음부터 다시 재생합니다. 자동 모드는 결과를 바로 보여 주므로, 과정을 보고 싶으면 이 버튼을 누르세요.</dd>
          <dt className="font-semibold">종목 · 엔진</dt>
          <dd>새 회의를 열 종목과 방식입니다. <b>DEMO(무료)</b>는 가짜 데이터로 화면만 시험합니다.
            <b> TradingAgents(유료)</b>는 실제 AI가 분석하며 1회 약 $0.04(약 50~60원), 2~3분이 걸립니다. 시작 전에 한 번 더 확인합니다.</dd>
          <dt className="font-semibold">새 분석 시작</dt>
          <dd>고른 종목과 엔진으로 <b>새 회의를 시작</b>합니다. 시작하면 바로 실시간으로 따라갑니다.</dd>
        </dl>

        <h3 className="mt-4 font-semibold text-[var(--mint)]">실시간으로도 볼 수 있나요?</h3>
        <p>네. 자동 모드에서는 진행 중인 회의를 알아서 보여 주고, ‘새 분석 시작’으로 시작하거나 ‘● 회의 중’ 카드를 눌러도 왼쪽 위에 <b>● 실시간</b>이 표시되고,
          AI가 한 단계를 끝낼 때마다 캐릭터가 바로 움직입니다. AI 한 단계가 수십 초씩 걸리기 때문에 중간에 조용한 시간이 있을 수 있습니다.
          끝난 회의를 고르면 <b>▶ 다시보기</b>로 재생됩니다.</p>

        <h3 className="mt-4 font-semibold text-[var(--mint)]">사무실과 표시</h3>
        <ul className="list-disc space-y-1 pl-5">
          <li><b>분석실</b>: 시장·뉴스 분석가가 책상에 앉아 조사합니다. <b>리서치 회의실</b>: 강세(초록)·약세(빨강) 연구원이 테이블에서 토론합니다.
            나머지 직원은 다음 단계에서 사무실에 들어오며, 지금은 오른쪽 ‘사무실 밖 직원’에 표시됩니다.</li>
          <li>머리 위 <b>…</b> 작업 중 · <b>✓</b> 완료 · <b className="text-rose-300">!</b> 실패</li>
          <li>말풍선은 발언의 <b>첫 문장만</b> 짧게 보여 줍니다. 직원을 클릭하면 오른쪽에서 전체 내용을 볼 수 있습니다.</li>
          <li>맨 위 노란 띠는 <b>지금 어느 단계인지</b> 쉬운 말로 알려 줍니다.</li>
          <li>마우스 드래그: 화면 이동 · 휠 또는 ±: 확대/축소 · 방향키: 이동</li>
        </ul>

        <h3 className="mt-4 font-semibold text-[var(--mint)]">결정을 어떻게 읽나요?</h3>
        <ul className="list-disc space-y-1 pl-5">
          <li><b>매수</b> 사자 · <b>매도</b> 팔자(줄이자) · <b>보유</b> 지켜보자 · <b>판단 보류</b> 근거 부족이라 사람 확인 필요</li>
          <li>AI 등급의 <b>비중 확대(Overweight)</b>는 ‘조금 더 사자’, <b>비중 축소(Underweight)</b>는 ‘조금 줄이자’는 뜻입니다.</li>
          <li>‘주의할 점’은 데이터가 일부 빠졌는지 등 결과를 믿기 전에 알아야 할 내용입니다.</li>
          <li>이 결정은 AI의 1회 의견입니다. 맞았는지는 아직 검증하지 않았으니 투자 신호로 쓰지 마세요.</li>
        </ul>
      </div>
    </div>
  );
}
