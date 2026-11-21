import { describe, expect, it } from 'vitest'
import { apply } from './Chat'

const usage = { inputTokens: 1, outputTokens: 2, cacheReadInputTokens: 0, cacheWriteInputTokens: 0 }

describe('apply', () => {
  it('names the skill on its tool row', () => {
    let m = apply({ role: 'agent', parts: [] }, { event: 'tool', data: { id: 't1', name: 'skills' } })
    m = apply(m, { event: 'tool', data: { id: 't2', name: 'shell' } })
    m = apply(m, { event: 'skill', data: { id: 't1', name: 'weekly-report' } })
    expect(m.parts).toEqual([
      { kind: 'tool', id: 't1', name: 'skills', skill: 'weekly-report' },
      { kind: 'tool', id: 't2', name: 'shell' },
    ])
  })

  it('keeps what the turn learned', () => {
    const m = apply({ role: 'agent', parts: [] }, { event: 'done', data: { stopReason: 'end_turn', usage, learned: ['weekly-report'] } })
    expect(m.learned).toEqual(['weekly-report'])
    expect(apply({ role: 'agent', parts: [] }, { event: 'done', data: { stopReason: 'end_turn', usage } }).learned).toBeUndefined()
  })
})
