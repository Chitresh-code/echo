import { unwrap } from './client'
import type { Usage } from './types'

export type TurnEvent =
  | { event: 'text'; data: { text: string } }
  | { event: 'tool'; data: { id: string; name: string } }
  // The skill a finished skills tool call loaded, sent after that call's tool row.
  | { event: 'skill'; data: { id: string; name: string } }
  // learned: skill folders the turn changed; missing when they could not be compared.
  | { event: 'done'; data: { stopReason: string; usage: Usage; learned?: string[] } }
  | { event: 'error'; data: { code: string; message: string; request_id?: string } }

/** Splits a server-sent event stream into events. Chunks can end anywhere, even mid-line, so the
 *  unfinished tail is kept for the next chunk. */
export class SseParser {
  private buffer = ''

  push(chunk: string): TurnEvent[] {
    this.buffer += chunk.replace(/\r\n?/g, '\n')
    const events: TurnEvent[] = []
    let end: number
    while ((end = this.buffer.indexOf('\n\n')) >= 0) {
      const block = this.buffer.slice(0, end)
      this.buffer = this.buffer.slice(end + 2)
      let name = 'message'
      const data: string[] = []
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) name = line.slice(6).trim()
        else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
      }
      if (data.length) events.push({ event: name, data: JSON.parse(data.join('\n')) } as TurnEvent)
    }
    return events
  }
}

/** POSTs a turn and yields its events as they arrive. A refused turn (a 4xx before the stream
 *  starts) throws ApiError like any other call. */
export async function* streamTurn(url: string, body: unknown, signal: AbortSignal): AsyncGenerator<TurnEvent> {
  const response = await fetch(url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok || !response.body) {
    await unwrap(response)
    return
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  const parser = new SseParser()
  for (;;) {
    const { done, value } = await reader.read()
    if (done) return
    yield* parser.push(value)
  }
}
