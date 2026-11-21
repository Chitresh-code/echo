// Monaco from this app's own bundle. @monaco-editor/react would otherwise fetch it from a CDN, which
// the Content Security Policy forbids, so the loader is pointed at the bundled copy.
import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import EditorWorker from 'monaco-editor/editor/editor.worker?worker'
import { TOKENS } from '../theme'

// Only the base editor worker: syntax colouring works for every language without the language
// service workers, and the editor is for reading and small edits, not an IDE's checks.
self.MonacoEnvironment = { getWorker: () => new EditorWorker() }
loader.config({ monaco })

// Monaco's theme colors take hex only, so the design's rgba() tints are converted.
function hex(color: string): string {
  const m = color.match(/rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)/)
  if (!m) return color
  const byte = (n: number) => Math.round(n).toString(16).padStart(2, '0')
  return `#${byte(+m[1])}${byte(+m[2])}${byte(+m[3])}${byte(+m[4] * 255)}`
}

for (const mode of ['dark', 'light'] as const) {
  const t = TOKENS[mode]
  monaco.editor.defineTheme(`echo-${mode}`, {
    base: mode === 'dark' ? 'vs-dark' : 'vs',
    inherit: true,
    rules: [],
    colors: {
      'editor.background': t.bg,
      'editorGutter.background': t.bg,
      'editorLineNumber.foreground': t.muted,
      'diffEditor.insertedLineBackground': hex(t.add),
      'diffEditor.removedLineBackground': hex(t.del),
      'diffEditor.insertedTextBackground': hex(t.add),
      'diffEditor.removedTextBackground': hex(t.del),
    },
  })
}
