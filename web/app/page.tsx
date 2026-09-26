'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import FindingCard from './components/FindingCard';
import AccountRiskPanel from './components/AccountRiskPanel';
import CopyFields from './components/CopyFields';
import HistoryPanel from './components/HistoryPanel';
import ImagePanel from './components/ImagePanel';
import ScoreGauge from './components/ScoreGauge';
import { API, apiHeaders } from '../lib/api';
import { describeError, describeFailure } from '../lib/errors';
import type { CheckResponse, Platform } from '../lib/types';

export default function Home() {
  const [platform, setPlatform] = useState<Platform>('google_ads');
  const [url, setUrl] = useState('');
  const [adCopy, setAdCopy] = useState('');
  // 제목·설명은 한 줄에 하나씩 받는다. 길이 한도는 필드별로 다르고,
  // 뭉뚱그린 한 덩어리로는 어느 필드인지 알 수 없다.
  const [headlines, setHeadlines] = useState('');
  const [descriptions, setDescriptions] = useState('');
  const [useLlm, setUseLlm] = useState(true);
  const [checkImages, setCheckImages] = useState(true);
  const [useVlm, setUseVlm] = useState(false);
  const [compareWithLast, setCompareWithLast] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CheckResponse | null>(null);
  const [error, setError] = useState('');
  const [elapsed, setElapsed] = useState(0);
  // 화면에 보이는 결과가 **어떤 설정으로** 나온 것인지 따로 기억한다.
  // 체크박스를 바꿨다고 이미 나온 결과의 패널이 사라지면 안 된다.
  const [ranWith, setRanWith] = useState({ images: true, vlm: false });
  const abortRef = useRef<AbortController | null>(null);

  // 최장 3분까지 걸릴 수 있는 요청이다. 아무 표시도 없으면 멈춘 걸로 보인다.
  useEffect(() => {
    if (!loading) return;
    const started = Date.now();
    const id = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 500);
    return () => clearInterval(id);
  }, [loading]);

  function cancel() {
    abortRef.current?.abort();
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError('');
    setResult(null);
    setElapsed(0);

    const controller = new AbortController();
    abortRef.current = controller;
    // 서버 데드라인(기본 180초)보다 넉넉히 잡아, 프록시가 멎어도 버튼이
    // '검사 중…'에 영원히 갇히지 않게 한다.
    const timer = setTimeout(() => controller.abort(), 200_000);
    const askedFor = { images: checkImages, vlm: checkImages && useVlm };

    try {
      const res = await fetch(`${API}/v1/check`, {
        method: 'POST',
        headers: apiHeaders({ 'Content-Type': 'application/json' }),
        signal: controller.signal,
        body: JSON.stringify({
          platform,
          url,
          ad_copy: adCopy,
          headlines: headlines.split('\n').map((l) => l.trim()).filter(Boolean),
          descriptions: descriptions.split('\n').map((l) => l.trim()).filter(Boolean),
          use_llm: useLlm,
          check_images: askedFor.images,
          use_vlm: askedFor.vlm,
          compare_with_last: compareWithLast,
        }),
      });
      if (!res.ok) throw new Error(await describeFailure(res));
      setResult(await res.json());
      setRanWith(askedFor);
    } catch (err) {
      setError(describeError(err));
    } finally {
      clearTimeout(timer);
      abortRef.current = null;
      setLoading(false);
    }
  }

  const count = (src: string) =>
    result?.findings.filter((f) => f.source === src).length ?? 0;
  const ruleCount = count('rule');
  const ocrCount = count('ocr');
  const llmCount = count('llm');
  const vlmCount = count('vlm');

  // 이미지 점검이 실제로 돌았는지 보여준다. 0건이 "문제 없음"인지
  // "아예 안 봤음"인지 구분이 안 되면 사용자가 알 수가 없다.
  const imagesFetched = result?.stats?.images_fetched;
  const imagesWithText = result?.stats?.images_with_text ?? 0;

  return (
    <main className="wrap">
      <header className="head">
        <p className="eyebrow">Ad Policy Precheck</p>
        <h1>광고 정책 사전 점검</h1>
        <p className="lead">
          랜딩 페이지와 광고 문구를 심사 전에 점검해, 어떤 항목으로 반려될 수 있는지 알려줍니다.
          결정적 룰셋이 먼저 판정하고, LLM 판단은 근거가 실제 페이지에 있을 때만 채택합니다.
        </p>
        <p className="nav"><Link href="/usage">토큰 사용량 보기 →</Link></p>
      </header>

      <form className="card form" onSubmit={onSubmit}>
        <div className="row">
          <label htmlFor="platform">플랫폼</label>
          <select
            id="platform"
            value={platform}
            onChange={(e) => setPlatform(e.target.value as Platform)}
          >
            <option value="google_ads">Google Ads</option>
            <option value="tiktok_ads">TikTok Ads</option>
          </select>
        </div>

        <div className="row">
          <label htmlFor="url">랜딩 페이지 URL</label>
          <input
            id="url"
            type="url"
            required
            placeholder="https://example.com/landing"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>

        <div className="row">
          <label htmlFor="copy">광고 문구 <span className="opt">선택</span></label>
          <textarea
            id="copy"
            rows={4}
            placeholder="실제로 집행할 광고 문구를 붙여 넣으세요."
            value={adCopy}
            onChange={(e) => setAdCopy(e.target.value)}
          />
        </div>

        <CopyFields
          headlines={headlines}
          descriptions={descriptions}
          onHeadlines={setHeadlines}
          onDescriptions={setDescriptions}
        />

        <div className="row inline">
          <input
            id="llm"
            type="checkbox"
            checked={useLlm}
            onChange={(e) => setUseLlm(e.target.checked)}
          />
          <label htmlFor="llm" className="cb">
            LLM 분석 사용 <span className="opt">끄면 룰셋만 실행 (빠름·재현성 100%)</span>
          </label>
        </div>

        <div className="row inline">
          <input
            id="images"
            type="checkbox"
            checked={checkImages}
            onChange={(e) => setCheckImages(e.target.checked)}
          />
          <label htmlFor="images" className="cb">
            이미지 속 문구 읽기 <span className="opt">배너에 박아 넣은 문구를 OCR로 확인</span>
          </label>
        </div>

        <div className="row inline">
          <input
            id="vlm"
            type="checkbox"
            checked={checkImages && useVlm}
            disabled={!checkImages}
            onChange={(e) => setUseVlm(e.target.checked)}
          />
          <label htmlFor="vlm" className="cb">
            이미지 자체 판정 <span className="opt">
              비포·애프터 등 글자 없는 문제. 멀티모달 서버 필요, 자동 검증 불가
            </span>
          </label>
        </div>

        <div className="row inline">
          <input
            id="compare"
            type="checkbox"
            checked={compareWithLast}
            onChange={(e) => setCompareWithLast(e.target.checked)}
          />
          <label htmlFor="compare" className="cb">
            지난 점검과 비교 <span className="opt">
              그 사이 본문이 바뀌었으면 지적으로 올립니다. 이미 심사를 통과한
              페이지일 때만 켜세요
            </span>
          </label>
        </div>

        <div className="actions">
          <button type="submit" disabled={loading || !url}>
            {loading ? `검사 중… ${elapsed}초` : '점검하기'}
          </button>
          {loading && (
            <button type="button" className="ghost" onClick={cancel}>
              중단
            </button>
          )}
        </div>
        {loading && (
          <p className="progress" aria-live="polite">
            페이지와 이미지를 가져와 점검하고 있습니다.
            {checkImages && ' 이미지가 많으면 1~3분 걸릴 수 있습니다.'}
          </p>
        )}
      </form>

      {error && (
        <div className="card alert" role="alert">
          {error}
        </div>
      )}

      {result && (
        <section className="result">
          <div className="card verdict-card">
            <ScoreGauge score={result.score} verdict={result.verdict} />
            <div className="verdict-body">
              <h2>{result.summary}</h2>
              <p className="meta">
                최종 URL <code>{result.final_url}</code>
              </p>
              <div className="chips">
                <span className="chip rule">룰셋 {ruleCount}건</span>
                {ocrCount > 0 && <span className="chip ocr">이미지 문구 {ocrCount}건</span>}
                <span className="chip llm">LLM {llmCount}건</span>
                {vlmCount > 0 && <span className="chip vlm">이미지 판정 {vlmCount}건</span>}
                {!result.llm_used && <span className="chip off">LLM 미사용</span>}
              </div>
              {imagesFetched !== undefined && (
                <p className="meta">
                  이미지 {imagesFetched}장을 확인했고, 그중 {imagesWithText}장에서 글자를 읽었습니다.
                  {imagesFetched === 0 && ' 읽을 만한 이미지가 없었습니다.'}
                </p>
              )}
              {result.llm_note && <p className="note">{result.llm_note}</p>}
            </div>
          </div>

          <HistoryPanel history={result.history} />

          <AccountRiskPanel risk={result.account_risk} />

          {ranWith.images && (
            <ImagePanel
              images={result.images ?? []}
              imagesFound={result.stats?.images_found ?? 0}
              vlmUsed={Boolean(result.vlm_used)}
              vlmNote={result.vlm_note ?? ''}
            />
          )}

          {result.findings.length === 0 ? (
            <div className="card empty">
              확인된 위반 항목이 없습니다. 다만 이 결과가 심사 통과를 보장하지는 않습니다.
            </div>
          ) : (
            <ul className="findings">
              {result.findings.map((f, i) => (
                <li key={`${f.source}-${f.code}-${f.image_url ?? ''}-${i}`}>
                  <FindingCard finding={f} />
                </li>
              ))}
            </ul>
          )}

          <p className="disclaimer">
            이 도구는 공개된 정책과 실무 반려 사례를 바탕으로 한 <strong>사전 점검 보조 도구</strong>입니다.
            최종 판단은 각 플랫폼의 공식 정책과 심사 결과를 따릅니다.
          </p>
        </section>
      )}
    </main>
  );
}
