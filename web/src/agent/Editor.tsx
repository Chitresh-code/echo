import Close from '@mui/icons-material/Close'
import { Alert, Box, Button, ButtonBase, CircularProgress, IconButton, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material'
import MonacoEditor, { DiffEditor, type OnMount } from '@monaco-editor/react'
import { useEffect, useRef, useState } from 'react'
import { MONO, useMode } from '../theme'
import type { OpenFiles } from './files'
import './monaco'

const options = {
  fontFamily: MONO,
  fontSize: 13,
  lineHeight: 22,
  minimap: { enabled: false },
  scrollBeyondLastLine: false,
  automaticLayout: true,
  renderWhitespace: 'selection' as const,
}

type Props = { agentId: string; files: OpenFiles; letters: Map<string, string> }

export function Editor({ agentId, files, letters }: Props) {
  const { mode } = useMode()
  const file = files.files.find((f) => f.path === files.active) ?? null
  const [cursor, setCursor] = useState({ line: 1, column: 1 })
  const [language, setLanguage] = useState('')
  // The save shortcut is bound once per editor, so it reads the current file through a ref.
  const saveRef = useRef(() => {})
  saveRef.current = () => file && files.save(file.path)
  const dirty = files.files.some((f) => f.value !== f.saved)

  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const onMount: OnMount = (editor, monaco) => {
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => saveRef.current())
    editor.onDidChangeCursorPosition((e) => setCursor({ line: e.position.lineNumber, column: e.position.column }))
    const showLanguage = () => setLanguage(editor.getModel()?.getLanguageId() ?? '')
    showLanguage()
    editor.onDidChangeModel(showLanguage)
  }

  // Each file gets its own model, keyed by agent and path, so undo history and scroll position
  // survive switching tabs.
  const modelPath = (prefix: string, path: string) => `file:///${prefix}/${agentId}/${path.split('/').map(encodeURIComponent).join('/')}`
  const changed = file ? letters.has(file.path) : false

  return (
    <Box component="section" aria-label="Editor" sx={{ display: 'flex', flexDirection: 'column', minHeight: 0, height: '100%', bgcolor: 'background.default' }}>
      <Box sx={{ display: 'flex', alignItems: 'stretch', borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper', minHeight: 41 }}>
        <Box role="tablist" sx={{ display: 'flex', overflowX: 'auto', flexGrow: 1 }}>
          {files.files.map((f) => {
            const selected = f.path === files.active
            const name = f.path.slice(f.path.lastIndexOf('/') + 1)
            return (
              <Box key={f.path} sx={{ display: 'flex', alignItems: 'center', borderBottom: 2, borderColor: selected ? 'primary.main' : 'transparent', flexShrink: 0 }}>
                <ButtonBase role="tab" aria-selected={selected} title={f.path} onClick={() => files.setActive(f.path)} sx={{ gap: 1, pl: 2, pr: 0.5, py: 1.25, fontSize: 13, color: selected ? 'text.primary' : 'text.secondary' }}>
                  {name}
                  {letters.get(f.path) && <Box component="span" sx={{ color: 'warning.main', fontFamily: MONO, fontSize: 11 }}>{letters.get(f.path)}</Box>}
                  {f.value !== f.saved && <Box component="span" aria-label="unsaved" sx={{ color: 'text.primary' }}>●</Box>}
                </ButtonBase>
                <IconButton size="small" aria-label={`Close ${name}`} onClick={() => files.close(f.path)} sx={{ mr: 0.5 }}>
                  <Close sx={{ fontSize: 14 }} />
                </IconButton>
              </Box>
            )
          })}
        </Box>
        {file && !file.binary && !file.error && (
          <ToggleButtonGroup
            size="small"
            exclusive
            value={file.mode}
            onChange={(_, value) => value && files.setMode(file.path, value)}
            aria-label="View"
            sx={{ my: 0.75, mx: 1.5, bgcolor: 'var(--raised)', '& .MuiToggleButton-root': { px: 1.5, py: 0.25, fontSize: 12, textTransform: 'none', border: 0 } }}
          >
            <ToggleButton value="edit">Edit</ToggleButton>
            <ToggleButton value="diff" disabled={!changed}>Diff</ToggleButton>
          </ToggleButtonGroup>
        )}
      </Box>

      {!file && (
        <Box sx={{ flexGrow: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', p: 3 }}>
          <Typography color="text.secondary">Open a file from the explorer to read or edit it.</Typography>
        </Box>
      )}

      {file && (
        <>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 1, px: 2, py: 1, borderBottom: 1, borderColor: 'divider', fontSize: 12, color: 'text.secondary' }}>
            <Box component="span" sx={{ fontFamily: MONO }}>{file.path}</Box>
            {file.mode === 'diff' && <span>· last commit to working tree</span>}
            <Box sx={{ flexGrow: 1 }} />
            {file.mode === 'edit' && !file.binary && !file.error && (
              <Button size="small" variant="outlined" disabled={file.value === file.saved} onClick={() => files.save(file.path)} sx={{ minHeight: 26, py: 0, borderRadius: '6px' }}>
                Save
              </Button>
            )}
          </Box>
          {file.changedOnDisk && (
            <Alert severity="warning" sx={{ borderRadius: 0 }} action={<Button color="inherit" size="small" onClick={() => files.reload(file.path)}>Reload</Button>}>
              Changed on disk. Reload to see the agent's version, or save to keep yours.
            </Alert>
          )}
          {file.error && <Alert severity="error" sx={{ borderRadius: 0 }}>{file.error}</Alert>}
          <Box sx={{ flexGrow: 1, minHeight: 300, position: 'relative' }}>
            {file.loading ? (
              <CircularProgress size={20} sx={{ m: 3 }} />
            ) : file.binary ? (
              <Typography color="text.secondary" sx={{ p: 3 }}>Binary file, not shown.</Typography>
            ) : file.error && !file.value ? null : file.mode === 'diff' ? (
              <DiffEditor
                original={file.head ?? ''}
                modified={file.value}
                originalModelPath={modelPath('head', file.path)}
                modifiedModelPath={modelPath('diff', file.path)}
                keepCurrentOriginalModel
                keepCurrentModifiedModel
                theme={`echo-${mode}`}
                options={{ ...options, readOnly: true, renderSideBySide: false }}
              />
            ) : (
              <MonacoEditor
                path={modelPath('edit', file.path)}
                value={file.value}
                onChange={(value) => files.update(file.path, { value: value ?? '' })}
                onMount={onMount}
                theme={`echo-${mode}`}
                options={options}
              />
            )}
          </Box>
          <Box component="footer" sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, px: 2, py: 0.75, borderTop: 1, borderColor: 'divider', bgcolor: 'background.paper', fontSize: 12, color: 'text.secondary' }}>
            {file.mode === 'edit' && !file.binary && (
              <>
                <span>{language}</span>
                <span>UTF-8</span>
                <span>Ln {cursor.line}, Col {cursor.column}</span>
              </>
            )}
            <Box sx={{ flexGrow: 1 }} />
            <span>{file.value !== file.saved ? 'Unsaved changes' : 'Saved in the workspace'}</span>
          </Box>
        </>
      )}
    </Box>
  )
}
