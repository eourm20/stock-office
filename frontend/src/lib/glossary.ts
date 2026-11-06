/** Plain-Korean meanings of the terms the company's documents use (owner, 2026-11-06: "the
 *  reports are jargon I cannot read"). Fixed text, no model: the same word always means the same. */
export const GLOSSARY: Record<string, string> = {
  RSI: "최근 오른 힘과 내린 힘을 0~100으로 잰 값이에요. 70을 넘으면 '너무 달아오름', 30 밑이면 '너무 식음'으로 봐요.",
  "200일선": "최근 200일(약 10개월) 평균 가격을 이은 선이에요. 주가가 이 위에 있으면 길게 봐서 오르는 흐름이에요.",
  "50일선": "최근 50일 평균 가격을 이은 선이에요. 주가가 이 위에 있으면 요즘 오르는 흐름이에요.",
  "20일선": "최근 20일 평균 가격을 이은 선이에요. 짧은 흐름을 볼 때 써요.",
  이동평균: "며칠 동안의 가격을 평균 내서 이은 선이에요. 들쭉날쭉한 가격의 큰 흐름을 보려고 써요.",
  "20일 고점": "최근 20일 중 가장 높았던 가격이에요.",
  "52주 고점": "최근 1년 중 가장 높았던 가격이에요.",
  눌림목: "오르던 주가가 잠깐 쉬면서 조금 내려온 자리예요. 다시 오를 때를 노리고 사는 자리로 봐요.",
  눌림: "오르던 주가가 잠깐 쉬면서 조금 내려온 것이에요.",
  과열: "너무 빨리 올라서 잠깐 쉬어 갈 가능성이 큰 상태예요.",
  모멘텀: "주가가 오르거나 내리는 기세예요.",
  지지선: "주가가 떨어지다가 멈추곤 하는 가격대예요.",
  저항선: "주가가 오르다가 막히곤 하는 가격대예요.",
  손절가: "이 가격까지 떨어지면 더 큰 손해를 막으려고 파는 선이에요.",
  손절: "손해를 보더라도 미리 정한 선에서 파는 것이에요. 더 큰 손해를 막으려는 거예요.",
  "본전 손절": "손절가를 산 가격까지 올려 둔 상태예요. 떨어져도 손해 없이 나올 수 있어요.",
  "시간 손절": "정해 둔 기간 안에 충분히 오르지 않으면 정리하는 규칙이에요.",
  목표가: "이 가격까지 오르면 팔아서 이익을 챙기려고 정한 가격이에요.",
  익절: "이익을 보고 파는 것이에요.",
  청산: "가지고 있던 주식을 모두 팔아 정리하는 것이에요.",
  지정가: "'이 가격보다 비싸게는 안 사겠다(싸게는 안 팔겠다)'고 값을 정해 내는 주문이에요.",
  시가: "그날 장이 열릴 때의 첫 가격이에요.",
  종가: "그날 장이 끝날 때의 마지막 가격이에요.",
  비중: "전체 돈 가운데 이 종목에 넣은 몫이에요.",
  "평가 손익": "지금 팔면 생길 이익이나 손해예요. 아직 팔지 않아서 확정된 건 아니에요.",
  "평균 단가": "여러 번 산 주식들의 평균 가격이에요.",
  예수금: "계좌에 주식을 사지 않고 남아 있는 현금이에요.",
  "추가 매수": "이미 가진 종목을 조금 더 사는 것이에요.",
  Overweight: "AI 위원회의 등급으로, '평소보다 조금 더 사자'는 의견이에요.",
  Underweight: "AI 위원회의 등급으로, '평소보다 줄이자'는 의견이에요.",
  "비중 확대": "그 종목에 넣는 돈을 늘리자는 의견이에요.",
  "비중 축소": "그 종목에 넣는 돈을 줄이자는 의견이에요.",
  변동성: "가격이 얼마나 크게 출렁이는지예요. 크면 오를 때도 내릴 때도 크게 움직여요.",
  ATR: "하루에 가격이 평균 얼마나 움직이는지 잰 값이에요. 손절가를 정할 때 참고해요.",
  거래량: "그날 사고판 주식 수예요. 많으면 그만큼 관심이 크다는 뜻이에요.",
  거래대금: "그날 사고판 금액이에요. 크면 쉽게 사고팔 수 있는 종목이에요.",
  시가총액: "회사 주식 전체의 값, 즉 회사의 크기예요.",
  PER: "회사가 1년에 버는 돈에 비해 주가가 몇 배인지예요. 높을수록 비싸게 평가받는 거예요.",
  PBR: "회사가 가진 재산에 비해 주가가 몇 배인지예요. 1보다 낮으면 재산보다 싸게 거래되는 거예요.",
  EPS: "주식 한 주가 1년에 번 이익이에요.",
  ROE: "회사가 자기 돈으로 1년에 얼마나 벌었는지 비율이에요. 높을수록 돈을 잘 굴리는 회사예요.",
  영업이익: "회사가 본업으로 번 이익이에요.",
  가이던스: "회사가 스스로 내놓은 앞으로의 실적 전망이에요.",
  컨센서스: "여러 증권사 전문가들이 예상한 실적의 평균이에요.",
  배당: "회사가 이익 일부를 주주에게 나눠 주는 돈이에요.",
  공매도: "주식을 빌려서 먼저 팔고 나중에 사서 갚는 것이에요. 주가가 내려야 돈을 벌어요.",
  유동성: "쉽게 사고팔 수 있는 정도, 또는 시장에 풀린 돈의 양이에요.",
  금리: "돈을 빌리는 값이에요. 오르면 기업과 사람들이 돈 쓰기를 망설여요.",
  환율: "다른 나라 돈과 바꾸는 비율이에요.",
  "1R": "처음에 정한 최대 손실 금액 한 단위예요. +1R은 그만큼 벌었다는 뜻이에요.",
};

const KEYS = Object.keys(GLOSSARY).sort((a, b) => b.length - a.length);
const LATIN = /[A-Za-z0-9]/;

export interface Piece { text: string; term?: string }

/** Splits text into plain pieces and glossary terms (longest match first; an English term only
 *  as a whole word; each term marked once per text so the page stays readable). */
export function splitTerms(text: string, extra: string[] = []): Piece[] {
  const keys = extra.length ? [...new Set([...KEYS, ...extra.filter((k) => k.trim().length > 1)])]
    .sort((a, b) => b.length - a.length) : KEYS;
  const out: Piece[] = [];
  const used = new Set<string>();
  let plain = "";
  let i = 0;
  while (i < text.length) {
    const key = keys.find((k) => !used.has(k) && text.startsWith(k, i) &&
      (!LATIN.test(k.charAt(0)) || ((i === 0 || !LATIN.test(text.charAt(i - 1))) &&
                             (i + k.length >= text.length || !LATIN.test(text.charAt(i + k.length))))));
    if (key) {
      if (plain) out.push({ text: plain });
      out.push({ text: key, term: key });
      used.add(key);
      plain = "";
      i += key.length;
    } else {
      plain += text.charAt(i);
      i += 1;
    }
  }
  if (plain) out.push({ text: plain });
  return out;
}
