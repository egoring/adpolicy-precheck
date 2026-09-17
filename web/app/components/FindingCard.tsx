import type { Finding } from '../../lib/types';

const SEVERITY_LABEL: Record<Finding['severity'], string> = {
  block: '게재 거부 위험',
  warn: '반려 가능',
  info: '개선 권장',
};

const SOURCE_LABEL: Record<Finding['source'], string> = {
  rule: '룰셋 판정',
  ocr: '이미지 속 문구',
  llm: 'LLM 판단',
  vlm: '이미지 판단',
};

// vlm은 인용할 문구가 없어 자동 검증이 불가능하다. 사용자가 그 사실을 알아야 한다.
const NEEDS_HUMAN_CHECK: Finding['source'] = 'vlm';

export default function FindingCard({ finding }: { finding: Finding }) {
  // 같은 지적이 배너 여러 장에서 나오면 카드를 여러 장 만들지 않고 여기 모은다.
  // 예전 API는 image_urls를 안 보내므로 image_url로 떨어진다.
  const images =
    finding.image_urls && finding.image_urls.length > 0
      ? finding.image_urls
      : finding.image_url
        ? [finding.image_url]
        : [];

  return (
    <article className={`card finding sev-${finding.severity}`}>
      <div className="finding-head">
        <span className={`badge sev-${finding.severity}`}>
          {SEVERITY_LABEL[finding.severity]}
        </span>
        <span className={`badge src-${finding.source}`}>
          {SOURCE_LABEL[finding.source]}
        </span>
        {finding.source === NEEDS_HUMAN_CHECK && (
          <span className="badge needs-check">직접 확인 필요</span>
        )}
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

      {images.length > 0 && (
        <p className="evidence image-source">
          <span className="evidence-label">
            {images.length > 1 ? `해당 이미지 ${images.length}장` : '해당 이미지'}
          </span>
          <span className="image-links">
            {images.map((url, i) => (
              <a key={url} href={url} target="_blank" rel="noreferrer noopener">
                {images.length > 1 ? `${i + 1}번` : url}
              </a>
            ))}
          </span>
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
