/**
 * Shared API utilities for ClassMate AI frontend.
 * All requests include credentials (session cookie) automatically.
 */

export const apiBase = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

type ApiError = { detail?: string };

export async function requestJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const r = await fetch(`${apiBase}/api${path}`, {
    ...init,
    credentials: "include",
    headers: { ...init?.headers },
  });
  const body = (await r.json()) as T & ApiError;
  if (!r.ok) {
    throw new Error(body.detail ?? `Request failed (${r.status}).`);
  }
  return body;
}

export function safeUrl(value: string | undefined | null): string | null {
  if (!value) return null;
  try {
    const u = new URL(value);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}

