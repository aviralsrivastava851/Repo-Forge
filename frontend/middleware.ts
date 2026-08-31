import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Frontend rate limiting: simple in-memory debounce for LLM-heavy routes
// Real limit is enforced by backend SlowAPI (10/min). This middleware adds client-side UX.

const WINDOW_MS = 60_000;
const LIMITS: Record<string, number> = {
  "/api/investigations": 60,
  "/new": 20,
};

const store = new Map<string, number[]>();

export function middleware(request: NextRequest) {
  const path = request.nextUrl.pathname;
  // only throttle API proxy if we proxy to backend; for now just pass through
  // NextRequest has no stable `ip` property in Next.js 15. Use the first
  // forwarded address when the app is behind a proxy, with a safe fallback.
  const clientIp = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "unknown";
  const key = `${clientIp}:${path}`;
  const now = Date.now();
  const arr = store.get(key) || [];
  const filtered = arr.filter((t) => now - t < WINDOW_MS);
  const limit = Object.entries(LIMITS).find(([k]) => path.startsWith(k))?.[1] ?? 60;
  if (filtered.length >= limit) {
    return NextResponse.json(
      { error: "Too Many Requests (frontend)", limit, retryAfter: 60 },
      { status: 429, headers: { "Retry-After": "60", "X-RateLimit-Limit": String(limit) } }
    );
  }
  filtered.push(now);
  store.set(key, filtered);
  return NextResponse.next();
}

export const config = {
  matcher: ["/api/:path*", "/new", "/investigations/:path*"],
};
