import type { Finding } from '../../lib/types';

const SEVERITY_LABEL: Record<Finding['severity'], string> = {
  block: '게재 거부 위험',
  warn: '반려 가능',
  info: '개선 권장',
};

const SOURCE_LABEL: Record<Finding['source'], string> = {
  rule: '룰셋 판정',
  llm: 'LLM 판단',
};

export default function FindingCard({ finding }: { finding: Finding }) {
  return (
    <article className={`card finding sev-${finding.severity}`}>
      <div className="finding-head">
        <span className={`badge sev-${finding.severity}`}>
          {SEVERITY_LABEL[finding.severity]}
        </span>
        <span className={`badge src-${finding.source}`}>
          {SOURCE_LABEL[finding.source]}
        </span>
        <code className="code">{finding.code}</code>
      </div>

      <h3>{finding.title}</h3>
      <p className="detail">{finding.detail}</p>

      {finding.evidence && (
        <p className="evidence">
          <span className="evidence-label">발견된 근거</span>
          <q>{finding.evidence}</q>
        </p>
      )}

      {finding.fix && (
        <p className="fix">
          <span className="fix-label">수정 방법</span>
          {finding.fix}
        </p>
      )}
    </article>
  );
}
