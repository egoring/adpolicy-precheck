import type { AccountRisk } from '../../lib/types';

/**
 * 계정 정지 위험 — 반려 점수와 다른 축이다.
 *
 * 반려 20건보다 정지 1건이 치명적인데, 점수 하나로 합치면 그 사실이 묻힌다.
 * 그래서 건수와 무관하게 가장 높은 등급을 맨 위에 크게 띄운다.
 */
const LEVEL: Record<AccountRisk['level'], { label: string; tone: string }> = {
  suspend: { label: '계정 즉시 정지 위험', tone: 'danger' },
  strike: { label: '경고 누적 (3진 아웃)', tone: 'caution' },
  disapprove: { label: '계정 정지 항목 없음', tone: 'ok' },
};

export default function AccountRiskPanel({ risk }: { risk?: AccountRisk }) {
  // 예전 API는 이 필드를 안 보낸다. 없으면 조용히 빠진다.
  if (!risk || !risk.level) return null;
  const level = LEVEL[risk.level] ?? LEVEL.disapprove;

  return (
    <section className={`card account-risk tone-${level.tone}`}>
      <header>
        <span className={`badge risk-${level.tone}`}>{level.label}</span>
        {risk.suspend_count > 0 && (
          <span className="risk-count">즉시 정지급 {risk.suspend_count}건</span>
        )}
        {risk.strike_count > 0 && (
          <span className="risk-count">경고 누적급 {risk.strike_count}건</span>
        )}
      </header>

      <p className="risk-note">{risk.note}</p>

      {risk.codes?.length > 0 && (
        <p className="risk-codes">
          {risk.codes.map((c) => (
            <code key={c}>{c}</code>
          ))}
        </p>
      )}
    </section>
  );
}
