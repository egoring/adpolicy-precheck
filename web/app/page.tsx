'use client';

import { useState } from 'react';
import FindingCard from './components/FindingCard';
import ScoreGauge from './components/ScoreGauge';
import type { CheckResponse, Platform } from '../lib/types';

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8080';

export default function Home() {
  const [platform, setPlatform] = useState<Platform>('google_ads');
  const [url, setUrl] = useState('');
  const [adCopy, setAdCopy] = useState('');
  const [useLlm, setUseLlm] = useState(true);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CheckResponse | null>(null);
  const [error, setError] = useState('');

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const res = await fetch(`${API}/v1/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform, url, ad_copy: adCopy, use_llm: useLlm }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail?.[0]?.msg ?? `요청 실패 (${res.status})`);
      }
      setResult(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : '알 수 없는 오류');
    } finally {
      setLoading(false);
    }
  }

  const ruleCount = result?.findings.filter((f) => f.source === 'rule').length ?? 0;
  const llmCount = result?.findings.filter((f) => f.source === 'llm').length ?? 0;

  return (
    <main className="wrap">
      <header className="head">
        <p className="eyebrow">Ad Policy Precheck</p>
        <h1>광고 정책 사전 점검</h1>
        <p className="lead">
          랜딩 페이지와 광고 문구를 심사 전에 점검해, 어떤 항목으로 반려될 수 있는지 알려줍니다.
          결정적 룰셋이 먼저 판정하고, LLM 판단은 근거가 실제 페이지에 있을 때만 채택합니다.
        </p>
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

        <button type="submit" disabled={loading || !url}>
          {loading ? '검사 중…' : '점검하기'}
        </button>
      </form>

      {error && <div className="card alert">{error}</div>}

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
                <span className="chip llm">LLM {llmCount}건</span>
                {!result.llm_used && <span className="chip off">LLM 미사용</span>}
              </div>
              {result.llm_note && <p className="note">{result.llm_note}</p>}
            </div>
          </div>

          {result.findings.length === 0 ? (
            <div className="card empty">
              확인된 위반 항목이 없습니다. 다만 이 결과가 심사 통과를 보장하지는 않습니다.
            </div>
          ) : (
            <ul className="findings">
              {result.findings.map((f) => (
                <li key={`${f.source}-${f.code}`}>
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
