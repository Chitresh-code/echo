import ArrowUpward from '@mui/icons-material/ArrowUpward'
import Stop from '@mui/icons-material/Stop'
import { Box, IconButton, Paper, Popper, Tooltip, Typography } from '@mui/material'
import { Slice } from '@tiptap/pm/model'
import { Placeholder } from '@tiptap/extensions'
import { Markdown } from '@tiptap/markdown'
import { EditorContent, Extension, useEditor, type Editor, type Range } from '@tiptap/react'
import { Suggestion } from '@tiptap/suggestion'
import StarterKit from '@tiptap/starter-kit'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { DRAFT_PREFIX } from '../auth'
import { MONO } from '../theme'
import { CommandMenu } from './CommandMenu'
import { parse, step, type Command, type CommandOption, type Parsed } from './commands'

// The api refuses a message longer than this; checked here on the same Markdown it receives.
export const MESSAGE_CHARS = 100_000
// The counter shows from here, so the limit is never a surprise.
const COUNTER_FROM = 90_000
const DRAFT_DELAY = 300

type Props = {
  /** Where the unsent text is kept in this tab: one per workspace, and "home". */
  draftKey: string
  /** No key yet, say: the box shows but takes no input. */
  disabled?: boolean
  /** A turn is running: typing is fine, sending is not, and the button stops the turn. */
  busy?: boolean
  /** Gets the message as Markdown; resolving false puts it back in the box. */
  onSend: (markdown: string) => Promise<boolean>
  onStop?: () => void
  /** Shown on the left under the text, such as the model and effort label. */
  footer?: ReactNode
  placeholder?: string
  autoFocus?: boolean
  /** Settings picked by typing `/` at the start of a line; never sent as a message. */
  commands?: Command[]
}

/** The `/` text being typed: where it is, what follows the slash, and where to show the menu. */
type Slash = { range: Range; query: string; rect: (() => DOMRect | null) | null }

// Read by screen readers only.
const visuallyHidden = { position: 'absolute', width: '1px', height: '1px', overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap' } as const

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

function readDraft(key: string): string {
  try {
    return sessionStorage.getItem(DRAFT_PREFIX + key) ?? ''
  } catch {
    return ''
  }
}

export function writeDraft(key: string, markdown: string) {
  try {
    if (markdown.trim()) sessionStorage.setItem(DRAFT_PREFIX + key, markdown)
    else sessionStorage.removeItem(DRAFT_PREFIX + key)
  } catch {
    // Private mode can refuse storage: the draft then lives as long as the page.
  }
}

/** The message box: Markdown by shortcut, sent as Markdown, drafts kept per tab. */
export function Composer({ draftKey, disabled = false, busy = false, onSend, onStop, footer, placeholder = 'Message Echo', autoFocus, commands = [] }: Props) {
  const [empty, setEmpty] = useState(() => !readDraft(draftKey).trim())
  const [length, setLength] = useState(0)
  const [tooLong, setTooLong] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  // The editor's key handler is made once, so it reads the latest props through here.
  const latest = useRef({ busy, disabled, onSend, draftKey })
  latest.current = { busy, disabled, onSend, draftKey }

  // The editor's own handlers below are made before it exists, so they reach it through here.
  const editorRef = useRef<Editor | null>(null)

  const menuId = useId()
  const [slash, setSlash] = useState<Slash | null>(null)
  const [active, setActive] = useState(0)
  const [said, setSaid] = useState('')
  const parsed: Parsed = slash ? parse(commands, slash.query) : { kind: 'none' }
  const rows: CommandOption[] = parsed.kind === 'names'
    ? parsed.names.map((c) => ({ id: c.name, label: `/${c.name}`, detail: c.description }))
    : parsed.kind === 'options' ? parsed.command.options(parsed.query) : []
  const open = parsed.kind !== 'none'
  const at = Math.min(active, Math.max(rows.length - 1, 0))

  // Each new filter starts on its first row that can be picked.
  useEffect(() => {
    setActive(Math.max(rows.findIndex((r) => !r.disabled), 0))
  }, [slash?.query])

  function pick(index: number) {
    const ed = editorRef.current
    const row = rows[index]
    if (!ed || !slash || !row || row.disabled) return
    if (parsed.kind === 'names') {
      // Completing the name keeps the menu open on that command's options.
      ed.chain().focus().insertContentAt(slash.range, { type: 'text', text: `/${row.id} ` }).run()
    } else if (parsed.kind === 'options') {
      const line = parsed.command.apply(row)
      if (line === null) return
      ed.chain().focus().deleteRange(slash.range).run()
      setSaid(line)
    }
  }

  // The editor's key handler runs before the suggestion plugin's, so the menu's keys are taken here.
  const menuKey = useRef<(event: KeyboardEvent) => boolean>(() => false)
  menuKey.current = (event) => {
    if (!open) return false
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      setActive(step(rows.length, at, event.key === 'ArrowDown' ? 1 : -1))
      return true
    }
    if ((event.key === 'Enter' || event.key === 'Tab') && !event.shiftKey && !event.metaKey && !event.ctrlKey) {
      // With no row, Enter still does nothing: a known command is never sent as a message.
      if (rows.length) pick(at)
      return parsed.kind === 'options' || rows.length > 0
    }
    return false
  }
  const openRef = useRef(open)
  openRef.current = open

  async function send(editor: Editor) {
    const { busy, disabled, onSend, draftKey } = latest.current
    const markdown = editor.getMarkdown().trim()
    if (busy || disabled || !markdown || openRef.current) return
    if (markdown.length > MESSAGE_CHARS) {
      setTooLong(true)
      setLength(markdown.length)
      return
    }
    clearTimeout(timer.current)
    editor.commands.clearContent(true)
    writeDraft(draftKey, '')
    if (!(await onSend(markdown))) {
      editor.commands.setContent(markdown, { contentType: 'markdown', emitUpdate: true })
    }
  }

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        // A message box, not a document: no headings, rules, strike or underline.
        heading: false,
        horizontalRule: false,
        strike: false,
        underline: false,
        // Only text that is plainly a link becomes one, so a file name like "hello.py" (a real
        // top level domain) stays text.
        link: { openOnClick: false, autolink: true, protocols: ['http', 'https', 'mailto'], shouldAutoLink: (text) => /^(https?:\/\/|mailto:|www\.)/i.test(text) },
      }),
      Markdown,
      Placeholder.configure({ placeholder }),
      Extension.create({
        name: 'slashCommands',
        addProseMirrorPlugins() {
          const show = (p: { range: Range; query: string; clientRect?: (() => DOMRect | null) | null }) => {
            setSaid('')
            setSlash({ range: p.range, query: p.query, rect: p.clientRect ?? null })
          }
          return [
            Suggestion({
              editor: this.editor,
              char: '/',
              startOfLine: true,
              allowSpaces: true,
              // Only at the very start of a paragraph or list item, never in code, so `/usr/bin`
              // in a code block or `/etc` after bold text stays text.
              allow: ({ state, range }) => {
                const $from = state.doc.resolve(range.from)
                return $from.parentOffset === 0 && !$from.parent.type.spec.code
              },
              render: () => ({ onStart: show, onUpdate: show, onExit: () => setSlash(null) }),
            }),
          ]
        },
      }),
    ],
    content: readDraft(draftKey),
    contentType: 'markdown',
    editable: !disabled,
    autofocus: autoFocus ? 'end' : false,
    editorProps: {
      attributes: { role: 'textbox', 'aria-multiline': 'true', 'aria-label': 'Message' },
      handleKeyDown(view, event): boolean {
        // Never while an input method is composing: Enter there picks a candidate.
        if (event.isComposing || view.composing) return false
        if (menuKey.current(event)) return true
        if (event.key !== 'Enter') return false
        const ed = editorRef.current
        if (!ed) return false
        const mod = event.metaKey || event.ctrlKey
        if (mod) {
          send(ed)
          return true
        }
        if (ed.isActive('codeBlock')) return false
        if (event.shiftKey) {
          // A new item in a list, else a new paragraph, so typing "- " or "1. " there starts a list.
          return ed.isActive('listItem') ? ed.commands.splitListItem('listItem') : ed.commands.splitBlock()
        }
        send(ed)
        return true
      },
      // Pasted plain text is read as Markdown, so a copied snippet keeps its formatting. Pasted
      // HTML goes through the schema instead, which keeps only the formatting enabled above.
      clipboardTextParser(text, $context, plain) {
        const ed = editorRef.current
        // No slice lets ProseMirror paste it as plain text: inside code, or with Shift held.
        if (plain || $context.parent.type.spec.code || !ed?.markdown) return undefined as unknown as Slice
        return Slice.maxOpen(ed.schema.nodeFromJSON(ed.markdown.parse(text)).content)
      },
    },
    onUpdate({ editor }) {
      setEmpty(editor.isEmpty)
      setTooLong(false)
      clearTimeout(timer.current)
      timer.current = setTimeout(() => {
        timer.current = undefined
        const markdown = editor.getMarkdown()
        setLength(markdown.length)
        writeDraft(latest.current.draftKey, markdown)
      }, DRAFT_DELAY)
    },
  })
  editorRef.current = editor

  useEffect(() => {
    editor.setEditable(!disabled)
  }, [editor, disabled])

  // A draft typed in the last moment before leaving is still kept.
  useEffect(
    () => () => {
      if (timer.current === undefined) return
      clearTimeout(timer.current)
      if (!editor.isDestroyed) writeDraft(latest.current.draftKey, editor.getMarkdown())
    },
    [editor],
  )

  // A textbox may point at the row it is on; screen readers then read the row as it changes.
  useEffect(() => {
    // Before the view mounts, and after it is torn down, Tiptap throws on any view access.
    if (editor.isDestroyed) return
    const dom = editor.view.dom
    if (open) dom.setAttribute('aria-controls', menuId)
    else dom.removeAttribute('aria-controls')
    if (open && rows.length) dom.setAttribute('aria-activedescendant', `${menuId}-${at}`)
    else dom.removeAttribute('aria-activedescendant')
  })

  const showCount = tooLong || length >= COUNTER_FROM
  return (
    <Box
      onClick={(e) => e.target === e.currentTarget && editor.commands.focus('end')}
      sx={{
        border: 1, borderColor: tooLong ? 'error.main' : 'divider', borderRadius: '14px', bgcolor: 'background.paper',
        opacity: disabled ? 0.6 : 1, '&:focus-within': { borderColor: tooLong ? 'error.main' : 'primary.main' },
        '& .tiptap': {
          outline: 'none', px: 2, pt: 1.5, pb: 0.5, maxHeight: '40vh', overflowY: 'auto', fontSize: 15, lineHeight: 1.55,
          '& p': { m: 0 }, '& ul, & ol': { my: 0.5, pl: 3 },
          '& blockquote': { m: 0, pl: 1.5, borderLeft: 3, borderColor: 'divider', color: 'text.secondary' },
          '& code': { fontFamily: MONO, fontSize: 13, px: 0.5, borderRadius: '4px', bgcolor: 'var(--raised)' },
          '& pre': { my: 0.5, p: 1.5, borderRadius: '8px', bgcolor: 'var(--raised)', overflowX: 'auto', '& code': { p: 0, bgcolor: 'transparent' } },
          '& a': { color: 'primary.main' },
          '& p.is-editor-empty:first-of-type::before': { content: 'attr(data-placeholder)', color: 'text.secondary', float: 'left', height: 0, pointerEvents: 'none' },
        },
      }}
    >
      <EditorContent editor={editor} />
      <Popper
        open={open && !!slash?.rect}
        anchorEl={slash?.rect ? { getBoundingClientRect: () => slash.rect?.() ?? new DOMRect() } : null}
        placement="top-start"
        sx={{ zIndex: 'modal' }}
      >
        <Paper elevation={4} sx={{ width: 340, maxWidth: 'calc(100vw - 32px)', border: 1, borderColor: 'divider', borderRadius: '10px' }}>
          <CommandMenu
            id={menuId}
            label={parsed.kind === 'options' ? parsed.command.description : 'Commands'}
            rows={rows}
            active={at}
            onPick={pick}
            onHover={setActive}
            empty={parsed.kind === 'options' ? `Nothing matches "${parsed.query}". Press Escape to send it as text.` : undefined}
          />
        </Paper>
      </Popper>
      <Box role="status" sx={visuallyHidden}>
        {said || (open ? (rows.length ? plural(rows.length, parsed.kind === 'names' ? 'command' : 'option') : 'Nothing matches') : '')}
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1, pb: 1, pt: 0.5 }}>
        <Box sx={{ flexGrow: 1, minWidth: 0 }}>{footer}</Box>
        {showCount && (
          <Typography role="status" color={tooLong ? 'error' : 'text.secondary'} sx={{ fontSize: 12, fontFamily: MONO }}>
            {tooLong ? `Too long to send: ${length.toLocaleString()} of ${MESSAGE_CHARS.toLocaleString()} characters` : `${length.toLocaleString()} / ${MESSAGE_CHARS.toLocaleString()}`}
          </Typography>
        )}
        {busy ? (
          <Tooltip title="Stop">
            <IconButton aria-label="Stop" onClick={onStop} sx={{ width: 34, height: 34, bgcolor: 'text.primary', color: 'background.paper', '&:hover': { bgcolor: 'text.secondary' } }}>
              <Stop fontSize="small" />
            </IconButton>
          </Tooltip>
        ) : (
          <IconButton
            aria-label="Send"
            disabled={disabled || empty}
            onClick={() => send(editor)}
            sx={{ width: 34, height: 34, bgcolor: 'primary.main', color: 'primary.contrastText', '&:hover': { bgcolor: 'primary.dark' }, '&.Mui-disabled': { bgcolor: 'var(--raised)' } }}
          >
            <ArrowUpward fontSize="small" />
          </IconButton>
        )}
      </Box>
    </Box>
  )
}
