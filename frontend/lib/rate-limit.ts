/**
 * Rate limit handling — parses 429 + Retry-After
 */
export interface RateLimitInfo {
  limit: number | null;
  remaining: number | null;
  reset: number | null;
  retryAfter: number | null;
}

export function parseRateLimitHeaders(headers: Headers): RateLimitInfo {
  return {
    limit: headers.get("X-RateLimit-Limit") ? parseInt(headers.get("X-RateLimit-Limit")!, 10) : null,
    remaining: headers.get("X-RateLimit-Remaining") ? parseInt(headers.get("X-RateLimit-Remaining")!, 10) : null,
    reset: headers.get("X-RateLimit-Reset") ? parseInt(headers.get("X-RateLimit-Reset")!, 10) : null,
    retryAfter: headers.get("Retry-After") ? parseInt(headers.get("Retry-After")!, 10) : null,
  };
}

export async function handleRateLimitedFetch(
  input: RequestInfo,
  init?: RequestInit
): Promise<{ response: Response; rateLimit: RateLimitInfo; isRateLimited: boolean }> {
  const response = await fetch(input, init);
  const rateLimit = parseRateLimitHeaders(response.headers);
  return {
    response,
    rateLimit,
    isRateLimited: response.status === 429,
  };
}

// Simple in-memory client-side debounce for LLM-heavy actions
const lastCall: Record<string, number> = {};

export function canCall(key: string, cooldownMs = 6000): boolean {
  const now = Date.now();
  const last = lastCall[key] || 0;
  if (now - last < cooldownMs) return false;
  lastCall[key] = now;
  return true;
}

export function getCooldownRemaining(key: string, cooldownMs = 6000): number {
  const last = lastCall[key] || 0;
  const elapsed = Date.now() - last;
  return Math.max(0, cooldownMs - elapsed);
}
