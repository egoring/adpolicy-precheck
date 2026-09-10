import type { CheckResponse } from '../../lib/types';

const VERDICT_LABEL: Record<CheckResponse['verdict'], string> = {
  pass: '통과 예상',
  review: '검토 필요',
  fail: '반려 위험',
};

const R = 52;
const C = 2 * Math.PI * R;

export default function ScoreGauge({
  score,
  verdict,
}: {
  score: number;
  verdict: CheckResponse['verdict'];
}) {
  const offset = C * (1 - score / 100);

  return (
    <div className={`gauge v-${verdict}`}>
      <svg viewBox="0 0 128 128" role="img" aria-label={`위험도 점수 ${score}점`}>
        <circle className="track" cx="64" cy="64" r={R} />
        <circle
          className="value"
          cx="64"
          cy="64"
          r={R}
          strokeDasharray={C}
          strokeDashoffset={offset}
          transform="rotate(-90 64 64)"
        />
      </svg>
      <div className="gauge-text">
        <strong>{score}</strong>
        <span>{VERDICT_LABEL[verdict]}</span>
      </div>
    </div>
  );
}
