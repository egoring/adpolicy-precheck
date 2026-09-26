'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import FindingCard from '../components/FindingCard';
import { API, apiHeaders } from '../../lib/api';
import { parseBatch, type BatchStatus } from '../../lib/batch';
import { describeError, describeFailure } from '../../lib/errors';
import { useIgnoredCodes } from '../../lib/ignore';
import type { Platform } from '../../lib/types';

const MAX_ITEMS = 50;
const POLL_MS = 2000;

const VERDICT_LABEL = { pass: '통과', review: '검토 필요', fail: '반려 위험' } as const;
const STATUS_LABEL = { queued: '대기', running: '점검 중', ok: '완료', error: '실패' } as const;
const RISK_LABEL = { suspend: '즉시 정지', strike: '경고 누적', disapprove: '-' } as const;

export default function BatchPage() {
  const [platform, setPlatform] = useState<Platform>('google_ads');
  const [text, setText] = useState('');
  const [useLlm, setUseLlm] = useState(false);
  const [checkImages, setCheckImages] = useState(false);
  const [jobId, setJobId] = useState('');
  const [status, setStatus] = useState<BatchStatus | null>(null);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const ignored = useIgnoredCodes();

  const parsed = parseBatch(text);
  const tooMany = parsed.rows.length > MAX_ITEMS;

  // 작업 번호가 생기면 끝날 때까지 결과를 받아 온다. 상태는 응답이 온 뒤에만 바꾼다.
  useEffect(() => {
    if (!jobId) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const res = await fetch(`${API}/v1/batch/${jobId}`, { headers: apiHeaders() });
        if (!res.ok) throw new Error(await describeFailure(res));
        const body: BatchStatus = await res.json();
        if (!alive) return;
        setStatus(body);
        if (body.status !== 'done') timer = setTimeout(poll, POLL_MS);
      } catch (e) {
        if (alive) setError(describeError(e));
      }
    };
    poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [jobId]);

  async function onFile(file: File) {
    setText(await file.text());
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setStatus(null);
    setSubmitting(true);
    try {
      const res = await fetch(`${API}/v1/batch`, {
        method: 'POST',
        headers: apiHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          items: parsed.rows.map((r) => ({
            platform,
            url: r.url,
            ad_copy: r.ad_copy,
            use_llm: useLlm,
            check_images: checkImages,
            ignore_codes: ignored,
          })),
        }),
      });
      if (!res.ok) throw new Error(await describeFailure(res));
      setJobId((await res.json()).job_id);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSubmitting(false);
    }
  }

  const running = Boolean(jobId) && status?.status !== 'done';

  return (
    <main className="wrap">
      <header className="head">
        <p className="eyebrow">AD POLICY PRECHECK</p>
        <h1>여러 건 한꺼번에 점검</h1>
        <p className="lead">
          캠페인 단위로 랜딩 페이지와 광고 문구를 한 번에 넣고, 끝나는 대로 결과를 확인하세요.
          최대 {MAX_ITEMS}건, 서버의 분당 한도 속도로 차례차례 점검합니다.
        </p>
        <p className="nav"><Link href="/">← 한 건씩 점검</Link></p>
      </header>

      <form className="card form" onSubmit={submit}>
        <div className="row">
          <label htmlFor="platform">플랫폼</label>
          <select id="platform" value={platform}
            onChange={(e) => setPlatform(e.target.value as Platform)}>
            <option value="google_ads">Google Ads</option>
            <option value="tiktok_ads">TikTok Ads</option>
          </select>
        </div>

        <div className="row">
          <label htmlFor="rows">
            점검 목록 <span className="opt">한 줄에 한 건 — URL, 광고 문구 (CSV·스프레드시트 붙여넣기 가능)</span>
          </label>
          <textarea id="rows" rows={8} value={text}
            placeholder={'https://example.com/a, 업계 1위 원두 브랜드\nhttps://example.com/b, 오늘만 50% 할인'}
            onChange={(e) => setText(e.target.value)} />
          <input type="file" accept=".csv,.tsv,.txt,text/csv" aria-label="CSV 파일 불러오기"
            onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
          <p className="meta">
            {parsed.rows.length}건 인식{tooMany && ` — 최대 ${MAX_ITEMS}건까지만 보낼 수 있습니다`}
            {ignored.length > 0 && ` · 무시할 지적 ${ignored.length}개 적용`}
          </p>
          {parsed.errors.length > 0 && (
            <ul className="parse-errors">
              {parsed.errors.slice(0, 5).map((m) => <li key={m}>{m}</li>)}
            </ul>
          )}
        </div>

        <div className="row inline">
          <input id="llm" type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
          <label htmlFor="llm" className="cb">
            LLM 분석 사용 <span className="opt">건마다 느려집니다</span>
          </label>
        </div>
        <div className="row inline">
          <input id="images" type="checkbox" checked={checkImages}
            onChange={(e) => setCheckImages(e.target.checked)} />
          <label htmlFor="images" className="cb">
            이미지 속 문구 읽기 <span className="opt">건마다 느려집니다</span>
          </label>
        </div>

        <div className="actions">
          <button type="submit"
            disabled={submitting || running || parsed.rows.length === 0 || tooMany}>
            {running ? `점검 중… ${status?.done ?? 0}/${status?.total ?? parsed.rows.length}`
              : `${parsed.rows.length}건 점검하기`}
          </button>
        </div>
      </form>

      {error && <p className="card alert" role="alert">{error}</p>}

      {status && (
        <section className="card">
          <p className="meta">
            {status.done}/{status.total}건 끝남{status.failed > 0 && ` · 실패 ${status.failed}건`}
            {status.status === 'done' ? ' · 모두 끝났습니다' : ''}
          </p>
          <div className="table-scroll">
            <table className="usage-table batch-table">
              <thead>
                <tr>
                  <th>#</th><th>URL</th><th>상태</th><th>판정</th><th>점수</th>
                  <th>계정 위험</th><th>지적</th>
                </tr>
              </thead>
              <tbody>
                {status.items.map((it) => {
                  const r = it.result;
                  return (
                    <tr key={it.index} className={r ? `verdict-${r.verdict}` : ''}>
                      <td>{it.index + 1}</td>
                      <td className="url">{it.url}</td>
                      <td>{STATUS_LABEL[it.status]}</td>
                      <td>{r ? VERDICT_LABEL[r.verdict] : it.error ? '-' : ''}</td>
                      <td>{r?.score ?? ''}</td>
                      <td>{r?.account_risk ? RISK_LABEL[r.account_risk.level] : ''}</td>
                      <td>{r ? r.findings.length : ''}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {status.items.filter((it) => it.error || (it.result?.findings.length ?? 0) > 0).map((it) => (
            <details key={it.index} className="batch-detail">
              <summary>
                #{it.index + 1} {it.url}{' '}
                <span className="opt">
                  {it.error ? '실패' : `지적 ${it.result!.findings.length}건`}
                </span>
              </summary>
              {it.error ? (
                <p className="card alert">{it.error}</p>
              ) : (
                <ul className="findings">
                  {it.result!.findings.map((f, i) => (
                    <li key={`${f.code}-${i}`}><FindingCard finding={f} /></li>
                  ))}
                </ul>
              )}
            </details>
          ))}
        </section>
      )}
    </main>
  );
}
