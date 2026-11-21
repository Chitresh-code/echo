import { expect, test } from 'vitest'
import { SseParser } from './stream'

test('every event type, across chunks split mid-line', () => {
  const body =
    'event: text\ndata: {"text": "Hel"}\n\n' +
    'event: tool\ndata: {"id": "t1", "name": "shell"}\n\n' +
    'event: done\ndata: {"stopReason": "end_turn", "usage": {"inputTokens": 3}}\n\n' +
    'event: error\ndata: {"code": "turn_failed", "message": "The turn failed."}\n\n'
  const parser = new SseParser()
  const events = []
  for (let i = 0; i < body.length; i += 7) events.push(...parser.push(body.slice(i, i + 7)))
  expect(events.map((e) => e.event)).toEqual(['text', 'tool', 'done', 'error'])
  expect(events[0].data).toEqual({ text: 'Hel' })
  expect(events[1].data).toEqual({ id: 't1', name: 'shell' })
})

test('multi-line data and CRLF line endings', () => {
  const events = new SseParser().push('event: text\r\ndata: {"text":\r\ndata: "a"}\r\n\r\n')
  expect(events).toEqual([{ event: 'text', data: { text: 'a' } }])
})
