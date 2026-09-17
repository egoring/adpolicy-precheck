import type { ImageReport } from '../../lib/types';

/**
 * 이미지에서 무엇을 읽었는지 그대로 보여준다.
 *
 * 지적이 없는 이미지도 남긴다. "읽었는데 걸리는 문구가 없었다"와
 * "아예 못 읽었다"는 완전히 다른 정보이고, 읽어낸 원문을 보여줘야
 * 사용자가 결과를 신뢰하거나 반박할 수 있다.
 */
export default function ImagePanel({
  images,
  imagesFound,
  vlmUsed,
  vlmNote,
}: {
  images: ImageReport[];
  /** 페이지에서 발견한 이미지 주소 개수. 가져온 장수와 다를 수 있다. */
  imagesFound: number;
  vlmUsed: boolean;
  vlmNote: string;
}) {
  const list = images ?? [];

  // 이미지 주소는 있었는데 한 장도 못 가져온 경우를 "이미지가 없다"로
  // 뭉뚱그리면 안 된다. 사용자가 원인을 찾을 수 없다.
  if (list.length === 0) {
    if (imagesFound > 0) {
      return (
        <section className="card images">
          <h3>이미지에서 읽은 문구</h3>
          <p className="meta">
            이미지 {imagesFound}개를 찾았지만 한 장도 가져오지 못했습니다. 접근이 막혀
            있거나 모두 상한에 걸렸을 수 있습니다.
          </p>
        </section>
      );
    }
    return null;
  }

  const withText = list.filter((i) => i.ocr_text).length;
  // 설정만 바꿔놓고 실제로는 예전 엔진이 도는 상황이 제일 나쁘다.
  // 무엇이 읽었는지 화면에 박아둔다.
  const engines = Array.from(
    new Set(list.map((i) => i.ocr_engine).filter((e): e is string => !!e))
  );
  const ENGINE_LABEL: Record<string, string> = {
    paddle: 'PaddleOCR 한국어 모델',
    tesseract: 'tesseract',
  };

  return (
    <section className="card images">
      <header className="images-head">
        <h3>이미지에서 읽은 문구</h3>
        <p className="meta">
          {imagesFound > list.length
            ? `발견한 ${imagesFound}개 중 ${list.length}장을 확인했고, `
            : `${list.length}장 중 `}
          {withText}장에서 글자를 읽었습니다.
          {withText > 0 && ' 아래 문구에 본문과 똑같은 룰을 적용했습니다.'}
          {engines.length > 0 && (
            <>
              {' '}
              읽은 엔진:{' '}
              <strong>{engines.map((e) => ENGINE_LABEL[e] ?? e).join(', ')}</strong>
            </>
          )}
        </p>
      </header>

      <ul className="image-list">
        {list.map((img, i) => {
          // 예전 버전 API가 이 필드를 안 보내면 렌더링 중에 터진다.
          const codes = img.finding_codes ?? [];
          const text = (img.ocr_text ?? '').trim();
          return (
            <li key={`${img.url}-${i}`} className={codes.length ? 'flagged' : ''}>
              <a
                href={img.url}
                target="_blank"
                rel="noreferrer noopener"
                className="thumb"
                aria-label="이미지 원본 열기"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={img.url} alt="" loading="lazy" />
              </a>

              <div className="image-body">
                <p className="image-meta">
                  {img.width > 0 && (
                    <span className="dim">
                      {img.width}×{img.height}
                    </span>
                  )}
                  {codes.length > 0 ? (
                    <span className="badge sev-block">
                      지적 {codes.length}건 · {codes.join(', ')}
                    </span>
                  ) : (
                    text && <span className="badge clean">걸리는 문구 없음</span>
                  )}
                </p>

                {text ? (
                  <pre className="ocr">{text}</pre>
                ) : (
                  <p className="ocr-none">{img.note || '읽어낼 글자가 없었습니다.'}</p>
                )}

                <a
                  className="image-url"
                  href={img.url}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  {img.url}
                </a>
              </div>
            </li>
          );
        })}
      </ul>

      <p className={`vlm-status${vlmUsed ? ' on' : ''}`}>
        <strong>이미지 자체 판정</strong> {vlmNote || (vlmUsed ? '실행됨' : '실행되지 않음')}
      </p>
    </section>
  );
}
