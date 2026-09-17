import type { CheckHistory } from '../../lib/types';

/**
 * 지난 점검과의 차이.
 *
 * 사전점검 도구를 실제로 쓰는 흐름은 "돌린다 → 고친다 → 다시 돌린다"다.
 * 그때 알고 싶은 건 전체 목록이 아니라 **무엇이 해결됐고 무엇이 새로
 * 생겼는지**다. 두 결과를 눈으로 대조하게 만들면 아무도 안 한다.
 */
function ago(ts: number): string {
  if (!ts) return '';
  const mins = Math.round((Date.now() - ts * 1000) / 60000);
  if (mins < 1) return '방금';
  if (mins < 60) return `${mins}분 전`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}시간 전`;
  return `${Math.round(hours / 24)}일 전`;
}

export default function HistoryPanel({ history }: { history?: CheckHistory | null }) {
  // 이 URL의 첫 점검이거나, 예전 API면 없다.
  if (!history) return null;

  const delta = history.score_delta ?? 0;
  const tone = delta > 0 ? 'better' : delta < 0 ? 'worse' : 'same';

  return (
    <section className="card history">
      <header className="history-head">
        <h3>지난 점검과 비교</h3>
        <span className="meta">{ago(history.previous_at)}</span>
      </header>

      <p className="history-score">
        <span className="from">{history.previous_score}</span>
        <span className="arrow" aria-label="에서">→</span>
        <span className={`to ${tone}`}>{history.previous_score + delta}</span>
        {delta !== 0 && (
          <span className={`delta ${tone}`}>
            {delta > 0 ? `+${delta}` : delta}
          </span>
        )}
      </p>

      <p className="meta">{history.note}</p>

      {history.content_changed && (
        <p className="history-changed">
          지난 점검 이후 <strong>본문이 바뀌었습니다.</strong> 광고가 이미 집행
          중이라면 바뀐 내용으로 다시 심사를 받아야 합니다.
        </p>
      )}

      {(history.resolved_codes?.length > 0 || history.new_codes?.length > 0) && (
        <div className="history-codes">
          {history.resolved_codes?.length > 0 && (
            <p>
              <span className="tag ok">해결됨</span>
              {history.resolved_codes.map((c) => (
                <code key={c}>{c}</code>
              ))}
            </p>
          )}
          {history.new_codes?.length > 0 && (
            <p>
              <span className="tag bad">새로 생김</span>
              {history.new_codes.map((c) => (
                <code key={c}>{c}</code>
              ))}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
