export type Platform = 'google_ads' | 'tiktok_ads';

export interface Finding {
  code: string;
  title: string;
  severity: 'block' | 'warn' | 'info';
  source: 'rule' | 'ocr' | 'llm' | 'vlm';
  detail: string;
  evidence: string;
  fix: string;
  /** 계정에 미치는 결과. 반려와 정지는 완전히 다른 사건이다. */
  enforcement?: Enforcement;
  /** 이미지에서 나온 지적이면 어느 이미지인지. 사용자가 직접 열어 확인한다. */
  image_url?: string;
  /** 같은 지적이 나온 이미지 전부. 예전 API는 안 보낸다. */
  image_urls?: string[];
}

export interface ImageReport {
  url: string;
  width: number;
  height: number;
  /** 이미지에서 읽어낸 문구. 비어 있으면 note에 이유가 있다. */
  ocr_text: string;
  note: string;
  finding_codes: string[];
  /** 실제로 읽은 엔진. 예전 API는 안 보낼 수 있다. */
  ocr_engine?: string;
}

export type Enforcement = 'suspend' | 'strike' | 'disapprove';

export interface AccountRisk {
  level: Enforcement;
  suspend_count: number;
  strike_count: number;
  codes: string[];
  note: string;
}

export interface UsageTotals {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  total_tokens: number;
  cost_usd: number;
  errors: number;
  duration_ms: number;
  images: number;
}

export interface UsageRow {
  ts: number;
  model?: string;
  images?: number;
  duration_ms?: number;
  total_tokens?: number;
  input_tokens?: number;
  output_tokens?: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  cost_usd?: number;
  error?: string;
}

export interface UsageReport {
  available: boolean;
  note?: string;
  totals?: UsageTotals;
  by_model?: Record<string, { calls: number; total_tokens: number; cost_usd: number }>;
  recent?: UsageRow[];
  log_path?: string;
}

export interface CheckHistory {
  previous_at: number;
  previous_fingerprint: string;
  previous_score: number;
  score_delta: number;
  content_changed: boolean;
  resolved_codes: string[];
  new_codes: string[];
  note: string;
}

export interface CheckResponse {
  platform: Platform;
  url: string;
  final_url: string;
  verdict: 'pass' | 'review' | 'fail';
  score: number;
  /** 계정 정지 위험. 예전 API는 안 보낸다. */
  account_risk?: AccountRisk;
  /** 본문 지문. 다음 점검 때 비교 기준이 된다. */
  content_fingerprint?: string;
  /** 지난 점검과의 차이. 첫 점검이면 없다. */
  history?: CheckHistory | null;
  summary: string;
  findings: Finding[];
  stats: Record<string, number>;
  images: ImageReport[];
  llm_used: boolean;
  llm_note: string;
  vlm_used: boolean;
  vlm_note: string;
}
