/**
 * Shared API utilities for ClassMate AI frontend.
 * All requests include credentials (session cookie) automatically.
 */

type ApiError = { detail?: unknown };

function getApiErrorMessage(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail.trim()) return detail;

  if (Array.isArray(detail)) {
    const messages = detail.flatMap((entry) => {
      if (!entry || typeof entry !== "object") return [];

      const error = entry as { loc?: unknown; msg?: unknown };
      if (typeof error.msg !== "string") return [];

      const location = Array.isArray(error.loc)
        ? error.loc.filter((part): part is string | number =>
            typeof part === "string" || typeof part === "number",
          )
        : [];
      const field = location.slice(1).join(".");
      return [field ? `${field}: ${error.msg}` : error.msg];
    });

    if (messages.length > 0) return messages.join(" ");
  }

  return `Request failed (${status}).`;
}

export async function requestJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let r: Response;
  try {
    r = await fetch(`/api${path}`, {
      ...init,
      credentials: "include",
      headers,
    });
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(
        "Could not connect to ClassMate AI. Check that the frontend and backend are running.",
      );
    }
    throw error;
  }

  const contentType = r.headers.get("content-type") ?? "";
  const body = contentType.includes("application/json")
    ? (await r.json()) as T & ApiError
    : null;
  if (!r.ok) {
    throw new Error(getApiErrorMessage(body?.detail, r.status));
  }
  if (body === null) {
    throw new Error("The ClassMate AI API returned an unexpected response.");
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
