/** API 호출 실패를 사용자가 행동할 수 있는 문장으로 바꾼다. */
import { API } from './api';

/** FastAPI의 detail은 검증 오류일 때만 배열이다. 문자열일 때를 놓치면
 *  504의 "check_images=false로 다시 시도하세요" 같은 안내가 통째로 사라진다. */
export async function describeFailure(res: Response): Promise<string> {
  const body = await res.json().catch(() => null);
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d as { msg?: string })?.msg)
      .filter((m): m is string => Boolean(m));
    if (msgs.length) return msgs.join(' · ');
  }
  if (res.status === 401) return 'API 키가 필요합니다. 웹을 빌드할 때 NEXT_PUBLIC_API_KEY를 넣었는지 확인하세요.';
  if (res.status === 504) return '점검이 서버 제한 시간을 넘겼습니다. 이미지 점검을 끄고 다시 시도해 보세요.';
  return `요청 실패 (${res.status})`;
}

export function describeError(err: unknown): string {
  if (err instanceof DOMException && err.name === 'AbortError') {
    return '점검을 중단했습니다.';
  }
  if (err instanceof TypeError) {
    // fetch가 TypeError를 던지는 건 네트워크·CORS 실패다. 'Failed to fetch'만
    // 보여주면 사용자가 무엇을 확인해야 할지 알 수 없다.
    return `API(${API})에 연결하지 못했습니다. 서버가 떠 있는지, CORS_ORIGINS에 이 주소가 들어 있는지 확인하세요.`;
  }
  return err instanceof Error ? err.message : '알 수 없는 오류';
}
