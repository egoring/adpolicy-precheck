/**
 * 무시할 지적 코드(C-5). 브라우저에 남겨 다음 점검에도 그대로 쓴다.
 *
 * useSyncExternalStore로 읽는다. 첫 렌더에서 localStorage를 직접 읽으면
 * 서버 렌더 결과(빈 목록)와 달라 하이드레이션이 어긋나고, effect에서
 * setState로 채우면 렌더가 한 번 더 연쇄된다.
 */
import { useMemo, useSyncExternalStore } from 'react';

const KEY = 'adpolicy.ignoreCodes';
const EVENT = 'adpolicy-ignore-change';

// 저장소를 못 쓰는 환경(사생활 보호 모드 등)에서도 이번 방문 동안은 동작하게.
let memory = '';

export function parseCodes(raw: string): string[] {
  const seen = new Set<string>();
  for (const part of raw.split(/[\s,]+/)) {
    const code = part.trim().toUpperCase();
    if (code) seen.add(code);
  }
  return [...seen];
}

function read(): string {
  try {
    return window.localStorage.getItem(KEY) ?? memory;
  } catch {
    return memory;
  }
}

export function writeIgnored(codes: string[]): void {
  memory = codes.join(',');
  try {
    window.localStorage.setItem(KEY, memory);
  } catch {
    // 저장이 안 돼도 memory로 이번 방문 동안은 유지된다.
  }
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(EVENT, onChange);
  window.addEventListener('storage', onChange); // 다른 탭에서 바꾼 경우
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener('storage', onChange);
  };
}

export function useIgnoredCodes(): string[] {
  const raw = useSyncExternalStore(subscribe, read, () => '');
  return useMemo(() => parseCodes(raw), [raw]);
}

export function withCode(codes: string[], code: string): string[] {
  return codes.includes(code) ? codes : [...codes, code];
}

export function withoutCode(codes: string[], code: string): string[] {
  return codes.filter((c) => c !== code);
}
