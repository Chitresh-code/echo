// Every API call goes through here: same-origin cookies, the response envelope unwrapped, and
// failures turned into ApiError with the API's stable code and its safe message.

export class ApiError extends Error {
  status: number
  code: string
  /** Extra facts some errors carry, such as the taken paths of an upload. */
  details: Record<string, unknown> | null
  constructor(status: number, code: string, message: string, details: Record<string, unknown> | null = null) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

let onUnauthorized = () => {}

/** Called on any 401, so an expired session sends the user back to sign in. */
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler
}

export async function unwrap<T>(response: Response): Promise<T> {
  let body: { success?: boolean; data?: T; error?: { code?: string; message?: string; details?: Record<string, unknown> | null } } | null = null
  try {
    body = await response.json()
  } catch {
    // Not JSON (a proxy error page, say): reported below by status.
  }
  if (response.ok && body?.success) return body.data as T
  if (response.status === 401) onUnauthorized()
  throw new ApiError(
    response.status,
    body?.error?.code ?? 'http_error',
    body?.error?.message ?? `The request failed (${response.status}).`,
    body?.error?.details ?? null,
  )
}

/** A FormData body is sent as multipart (the browser sets its boundary); anything else as JSON. */
export async function api<T>(path: string, options: { method?: string; body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  const { method = 'GET', body, signal } = options
  const form = body instanceof FormData
  const response = await fetch(path, {
    method,
    credentials: 'same-origin',
    headers: body === undefined || form ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : form ? body : JSON.stringify(body),
    signal,
  })
  return unwrap<T>(response)
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong.'
}
