export type Platform = 'google_ads' | 'tiktok_ads';

export interface Finding {
  code: string;
  title: string;
  severity: 'block' | 'warn' | 'info';
  source: 'rule' | 'llm';
  detail: string;
  evidence: string;
  fix: string;
}

export interface CheckResponse {
  platform: Platform;
  url: string;
  final_url: string;
  verdict: 'pass' | 'review' | 'fail';
  score: number;
  summary: string;
  findings: Finding[];
  stats: Record<string, number>;
  llm_used: boolean;
  llm_note: string;
}
