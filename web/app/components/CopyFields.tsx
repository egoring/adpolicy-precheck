'use client';

/**
 * 광고 제목·설명 입력. 한 줄에 하나씩.
 *
 * 여기서 제일 중요한 건 **입력칸이 아니라 옆에 붙는 숫자**다. Google은
 * 한국어 문자 한 개를 두 자로 세므로 제목의 실질 한도가 15자인데, 이걸
 * 모르고 영문 기준 30자로 써 두는 경우가 많다. 점검을 돌리기 전에
 * 타이핑하는 동안 바로 보이는 게 낫다.
 */
const HEADLINE_LIMIT = 30;
const DESCRIPTION_LIMIT = 90;

/** 서버의 adcopy.width()와 같은 방식으로 센다. 두 곳이 다르면 안 된다. */
export function adWidth(text: string): number {
  let total = 0;
  for (const ch of text) {
    const code = ch.codePointAt(0) ?? 0;
    const wide =
      (code >= 0x1100 && code <= 0x115f) ||
      (code >= 0x2e80 && code <= 0xa4cf) ||
      (code >= 0xac00 && code <= 0xd7a3) ||
      (code >= 0xf900 && code <= 0xfaff) ||
      (code >= 0xfe30 && code <= 0xfe6f) ||
      (code >= 0xff00 && code <= 0xff60) ||
      (code >= 0xffe0 && code <= 0xffe6) ||
      (code >= 0x1f300 && code <= 0x1fbff);
    total += wide ? 2 : 1;
  }
  return total;
}

function Counter({ lines, limit }: { lines: string[]; limit: number }) {
  const rows = lines.filter((l) => l.trim());
  if (rows.length === 0) return null;
  return (
    <ul className="counter">
      {rows.map((line, i) => {
        const w = adWidth(line);
        return (
          <li key={i} className={w > limit ? 'over' : ''}>
            <span className="n">{w}</span>
            <span className="slash">/{limit}</span>
            <span className="txt">{line.slice(0, 30)}</span>
            {w > limit && <span className="badge">{w - limit}자 초과</span>}
          </li>
        );
      })}
    </ul>
  );
}

export default function CopyFields({
  headlines,
  descriptions,
  onHeadlines,
  onDescriptions,
}: {
  headlines: string;
  descriptions: string;
  onHeadlines: (v: string) => void;
  onDescriptions: (v: string) => void;
}) {
  const hLines = headlines.split('\n');
  const dLines = descriptions.split('\n');

  return (
    <details className="copyfields">
      <summary>
        제목·설명을 나눠서 입력 <span className="opt">글자 수 한도를 함께 점검합니다</span>
      </summary>

      <p className="hint">
        한국어는 <strong>문자 한 개가 두 자로 계산</strong>됩니다. 제목은 한글 15자(영문 30자),
        설명은 한글 45자(영문 90자)가 실질 한도입니다.
      </p>

      <div className="row">
        <label htmlFor="headlines">광고 제목 <span className="opt">한 줄에 하나</span></label>
        <textarea
          id="headlines"
          rows={3}
          placeholder={'갓 볶은 원두 정기배송\n첫 주문 30% 할인'}
          value={headlines}
          onChange={(e) => onHeadlines(e.target.value)}
        />
        <Counter lines={hLines} limit={HEADLINE_LIMIT} />
      </div>

      <div className="row">
        <label htmlFor="descriptions">광고 설명 <span className="opt">한 줄에 하나</span></label>
        <textarea
          id="descriptions"
          rows={3}
          placeholder="매주 로스팅한 원두를 집으로 보내드립니다. 무료 배송."
          value={descriptions}
          onChange={(e) => onDescriptions(e.target.value)}
        />
        <Counter lines={dLines} limit={DESCRIPTION_LIMIT} />
      </div>
    </details>
  );
}
