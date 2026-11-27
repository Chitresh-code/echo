import type { Editor } from '@tiptap/react'
import { act } from 'react'

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

export const ok = (data: unknown) => new Response(JSON.stringify({ success: true, data }), { status: 200 })
export const refused = (status: number, code: string, message: string) =>
  new Response(JSON.stringify({ success: false, error: { code, message } }), { status })

/** jsdom has no media queries or layout: the wide layout, and an empty caret rectangle for ProseMirror. */
export function fakeLayout() {
  globalThis.matchMedia = ((query: string) => ({
    matches: query.includes('min-width'), media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
  })) as unknown as typeof matchMedia
  Range.prototype.getClientRects = () => ({ length: 0, item: () => null, [Symbol.iterator]: [][Symbol.iterator] }) as unknown as DOMRectList
  Range.prototype.getBoundingClientRect = () => new DOMRect()
}

export const messageBox = () => document.querySelector('[role="textbox"][aria-label="Message"]') as HTMLElement & { editor: Editor }

/** Types as a keystroke does, through the text input hook, so shortcuts such as `**a**` and `- ` apply. */
export async function typeMessage(text: string) {
  await act(async () => {
    const { view } = messageBox().editor
    for (const ch of text) {
      const { from, to } = view.state.selection
      const insert = () => view.state.tr.insertText(ch, from, to)
      if (!view.someProp('handleTextInput', (f) => f(view, from, to, ch, insert))) view.dispatch(insert())
    }
  })
}

export async function press(el: HTMLElement, key: string, init: KeyboardEventInit = {}) {
  await act(async () => {
    el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init }))
  })
}

export async function click(el: HTMLElement) {
  await act(async () => el.click())
}

/** Lets fetches, stream reads and the renders they cause finish. */
export async function settle() {
  for (let i = 0; i < 5; i++) await act(async () => new Promise((r) => setTimeout(r, 10)))
}
