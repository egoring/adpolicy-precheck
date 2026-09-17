'use client';

import { useCallback, useEffect, useState } from 'react';
import type { UsageReport, UsageRow } from '../../lib/types';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

const RANGES: { label: string; hours: number }[] = [
  { label: '전체', hours: 0 },
  { label: '최근 1시간', hours: 1 },
  { label: '오늘', hours: 24 },
  { label: '최근 7일', hours: 24 * 7 },
];

function n(v: number | undefined): string {
  return (v ?? 0).toLocaleString('ko-KR');
}

function when(ts: number): string {
  return new Date(ts * 1000).toLocaleString('ko-KR', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    second: '2-digit',
  });
}

/**
 * 호출별 토큰을 막대로 그린다.
 *
 * 차트 라이브러리를 넣지 않았다. 값 하나짜리 막대 그래프를 그리자고 번들에
 * 수백 KB를 더할 이유가 없고, 이 화면은 "얼마나 썼나"만 답하면 된다.
 */
function Bars({ rows }: { rows: UsageRow[] }) {
  const series = rows.slice(0, 40).reverse();
  const max = Math.max(1, ...series.map((r) => r.total_tokens ?? 0));
  if (series.length === 0) return null;

  return (
    <div className="usage-bars" role="img" aria-label="호출별 토큰 사용량">
      {series.map((r, i) => {
        const total = r.total_tokens ?? 0;
        const pct = Math.max(2, Math.round((total / max) * 100));
        return (
          <div
            key={`${r.ts}-${i}`}
            className={`bar${r.error ? ' failed' : ''}`}
            style={{ height: `${pct}%` }}
            title={`${when(r.ts)} · ${n(total)} 토큰${r.error ? ' · 실패' : ''}`}
          />
        );
      })}
    </div>
  );
}

export default function UsagePage() {
  const [hours, setHours] = useState(0);
  const [data, setData] = useState<UsageReport | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (h: number) => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API}/v1/usage?hours=${h}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e) {
      setError(
        e instanceof TypeError
          ? `API(${API})에 연결할 수 없습니다. 컨테이너가 떠 있는지 확인하세요.`
          : `사용량을 불러오지 못했습니다: ${String(e)}`,
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(hours);
    // 30초마다 갱신. 점검을 돌리는 동안 숫자가 올라가는 걸 볼 수 있어야 한다.
    const t = setInterval(() => load(hours), 30_000);
    return () => clearInterval(t);
  }, [hours, load]);

  const t = data?.totals;
  const rows = data?.recent ?? [];
  const avgMs = t && t.calls > 0 ? Math.round(t.duration_ms / t.calls) : 0;
  const avgTok = t && t.calls > 0 ? Math.round(t.total_tokens / t.calls) : 0;

  return (
    <main className="wrap">
      <header className="head">
        <p className="eyebrow">AD POLICY PRECHECK</p>
        <h1>토큰 사용량</h1>
        <p className="lead">
          Claude 다리가 기록한 실제 사용량입니다. 점검 한 번에 얼마나 쓰는지,
          무엇이 비싼지 여기서 확인하세요.
        </p>
        <p className="nav"><a href="/">← 점검 화면으로</a></p>
      </header>

      <div className="range-tabs" role="tablist">
        {RANGES.map((r) => (
          <button
            key={r.hours}
            type="button"
            role="tab"
            aria-selected={hours === r.hours}
            className={hours === r.hours ? 'on' : ''}
            onClick={() => setHours(r.hours)}
          >
            {r.label}
          </button>
        ))}
        <button type="button" className="refresh" onClick={() => load(hours)}>
          새로고침
        </button>
      </div>

      {error && <p className="card alert" role="alert">{error}</p>}

      {!error && data && !data.available && (
        <section className="card">
          <h3>사용량을 가져올 수 없습니다</h3>
          <p className="meta">{data.note}</p>
          <p className="meta">
            이 화면은 <code>bridge/claude_bridge.py</code>가 LLM 백엔드일 때만
            숫자를 보여줍니다. vLLM이나 OpenAI로 돌리는 중이라면 그쪽 사용량은
            해당 서비스에서 확인해야 합니다.
          </p>
        </section>
      )}

      {t && (
        <>
          <section className="usage-tiles">
            <div className="tile">
              <span className="tile-value">{n(t.total_tokens)}</span>
              <span className="tile-label">총 토큰</span>
            </div>
            <div className="tile">
              <span className="tile-value">{n(t.calls)}</span>
              <span className="tile-label">
                호출{t.errors > 0 && <em> · 실패 {n(t.errors)}</em>}
              </span>
            </div>
            <div className="tile">
              <span className="tile-value">{n(avgTok)}</span>
              <span className="tile-label">호출당 평균 토큰</span>
            </div>
            <div className="tile">
              <span className="tile-value">
                ${(t.cost_usd ?? 0).toFixed(3)}
              </span>
              <span className="tile-label">환산 비용(참고)</span>
            </div>
          </section>

          <section className="card">
            <h3>토큰 구성</h3>
            <p className="meta">
              캐시 읽기가 본 입력보다 큰 것이 보통입니다. 이걸 빼고 세면 실제
              사용량을 크게 낮잡게 됩니다.
            </p>
            <dl className="usage-breakdown">
              <div><dt>입력</dt><dd>{n(t.input_tokens)}</dd></div>
              <div><dt>출력</dt><dd>{n(t.output_tokens)}</dd></div>
              <div><dt>캐시 읽기</dt><dd>{n(t.cache_read_tokens)}</dd></div>
              <div><dt>캐시 생성</dt><dd>{n(t.cache_write_tokens)}</dd></div>
              <div><dt>평균 소요</dt><dd>{n(avgMs)} ms</dd></div>
              <div><dt>이미지 전달</dt><dd>{n(t.images)}장</dd></div>
            </dl>
          </section>

          <section className="card">
            <h3>최근 호출</h3>
            <Bars rows={rows} />
            <div className="table-scroll">
              <table className="usage-table">
                <thead>
                  <tr>
                    <th>시각</th><th>모델</th><th className="num">토큰</th>
                    <th className="num">입력</th><th className="num">출력</th>
                    <th className="num">캐시</th><th className="num">이미지</th>
                    <th className="num">소요</th><th>상태</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={`${r.ts}-${i}`} className={r.error ? 'failed' : ''}>
                      <td>{when(r.ts)}</td>
                      <td className="model">{r.model ?? '-'}</td>
                      <td className="num">{n(r.total_tokens)}</td>
                      <td className="num">{n(r.input_tokens)}</td>
                      <td className="num">{n(r.output_tokens)}</td>
                      <td className="num">
                        {n((r.cache_read_tokens ?? 0) + (r.cache_write_tokens ?? 0))}
                      </td>
                      <td className="num">{r.images ? n(r.images) : '-'}</td>
                      <td className="num">{n(r.duration_ms)} ms</td>
                      <td>{r.error ? <span className="fail">{r.error}</span> : '완료'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rows.length === 0 && !loading && (
              <p className="meta">아직 기록이 없습니다. 점검을 한 번 돌려보세요.</p>
            )}
          </section>

          {data?.log_path && (
            <p className="meta foot">
              원본 기록: <code>{data.log_path}</code>
            </p>
          )}
        </>
      )}
    </main>
  );
}
