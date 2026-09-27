/**
 * 배치 입력 파싱 (C-4). 한 줄에 한 건 — `URL, 광고 문구`.
 *
 * 스프레드시트에서 복사하면 탭으로, CSV 파일이면 쉼표와 따옴표로 온다.
 * 광고 문구에는 쉼표가 흔하므로 따옴표 규칙(RFC 4180)을 지킨다.
 */
import type { CheckResponse } from './types';

export interface BatchRow {
  url: string;
  ad_copy: string;
}

function splitLine(line: string): string[] {
  if (line.includes('\t')) return line.split('\t');
  const out: string[] = [];
  let cur = '';
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quoted) {
      if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; }
      else if (ch === '"') quoted = false;
      else cur += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') { out.push(cur); cur = ''; }
    else cur += ch;
  }
  out.push(cur);
  return out;
}

export function parseBatch(text: string): { rows: BatchRow[]; errors: string[] } {
  const rows: BatchRow[] = [];
  const errors: string[] = [];
  text.split(/\r?\n/).forEach((raw, i) => {
    if (!raw.trim()) return;
    const [first = '', ...rest] = splitLine(raw).map((c) => c.trim());
    if (i === 0 && /^url$/i.test(first)) return; // 머리글
    if (!/^https?:\/\//i.test(first)) {
      errors.push(`${i + 1}번째 줄: URL은 http:// 또는 https://로 시작해야 합니다`);
      return;
    }
    rows.push({ url: first, ad_copy: rest.join(', ').trim() });
  });
  return { rows, errors };
}

export interface BatchItem {
  index: number;
  url: string;
  status: 'queued' | 'running' | 'ok' | 'error';
  result: CheckResponse | null;
  error: string;
}

export interface BatchStatus {
  job_id: string;
  status: 'queued' | 'running' | 'done';
  total: number;
  done: number;
  failed: number;
  items: BatchItem[];
}
