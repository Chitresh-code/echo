import ChevronRight from '@mui/icons-material/ChevronRight'
import CreateNewFolderOutlined from '@mui/icons-material/CreateNewFolderOutlined'
import ExpandMore from '@mui/icons-material/ExpandMore'
import FileUploadOutlined from '@mui/icons-material/FileUploadOutlined'
import FolderOutlined from '@mui/icons-material/FolderOutlined'
import InsertDriveFileOutlined from '@mui/icons-material/InsertDriveFileOutlined'
import NoteAddOutlined from '@mui/icons-material/NoteAddOutlined'
import Refresh from '@mui/icons-material/Refresh'
import {
  Alert, Box, Button, ButtonBase, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, InputBase, Tooltip, Typography,
} from '@mui/material'
import { useMemo, useRef, useState, type DragEvent, type ReactNode } from 'react'
import { api, ApiError, errorText } from '../api/client'
import type { Storage, Tree } from '../api/types'
import { bytes, storageLevel } from '../format'
import { MONO } from '../theme'
import { buildRows, nameProblem, parents, type Row } from './tree'

// The api's limits, checked here first so a too-big upload is refused before it is sent.
const MAX_FILE = 5 * 1024 * 1024
const MAX_FILES = 20
const MAX_TOTAL = 25 * 1024 * 1024

export type NewKind = 'file' | 'folder'

type Props = {
  agentId: string
  tree: Tree | null
  letters: Map<string, string>
  active: string | null
  onOpen: (path: string) => void
  onRefresh: () => void
  /** Makes the file or folder; a failure is thrown and shown at the name box. */
  onCreate: (kind: NewKind, path: string) => Promise<void>
  storage: Storage | null
}

type Naming = { kind: NewKind; folder: string; name: string; error: string; busy: boolean }
type Conflict = { folder: string; files: File[]; taken: string[] }

const folderOf = (path: string) => (path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '')
const join = (folder: string, name: string) => (folder ? `${folder}/${name}` : name)
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

export function Explorer({ agentId, tree, letters, active, onOpen, onRefresh, onCreate, storage }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  // The row last clicked: where New file, New folder and Upload put things. Not the same as the open tab.
  const [selected, setSelected] = useState<{ path: string; dir: boolean } | null>(null)
  const [naming, setNaming] = useState<Naming | null>(null)
  const [dropOn, setDropOn] = useState<string | null>(null)
  const [uploading, setUploading] = useState('')
  const [notice, setNotice] = useState<{ severity: 'success' | 'error'; text: string } | null>(null)
  const [conflict, setConflict] = useState<Conflict | null>(null)
  const picker = useRef<HTMLInputElement>(null)
  // Enter disables the box, which blurs it: without this the blur would send the same create twice.
  const creating = useRef(false)
  const entries = useMemo(() => tree?.entries ?? [], [tree])
  const rows = useMemo(() => buildRows(entries, letters, expanded), [entries, letters, expanded])

  const target = selected ? (selected.dir ? selected.path : folderOf(selected.path)) : folderOf(active ?? '')

  const expand = (paths: string[]) => setExpanded((all) => new Set([...all, ...paths]))
  const toggle = (path: string) =>
    setExpanded((all) => {
      const next = new Set(all)
      if (!next.delete(path)) next.add(path)
      return next
    })

  function startNaming(kind: NewKind, folder: string) {
    if (folder) expand([...parents(folder), folder])
    setNaming({ kind, folder, name: '', error: '', busy: false })
  }

  async function finishNaming(force: boolean) {
    if (!naming || creating.current) return
    const problem = nameProblem(naming.name, entries, naming.folder)
    // Clicking away with nothing typed cancels, as in VS Code; with a bad name it cancels too, since
    // the box is gone and the message would have nowhere to show.
    if (problem) return force ? setNaming({ ...naming, error: problem }) : setNaming(null)
    const path = join(naming.folder, naming.name.trim().replace(/\/+$/, ''))
    setNaming({ ...naming, busy: true, error: '' })
    creating.current = true
    try {
      await onCreate(naming.kind, path)
      expand(naming.kind === 'folder' ? [...parents(path), path] : parents(path))
      setSelected({ path, dir: naming.kind === 'folder' })
      setNaming(null)
    } catch (e) {
      setNaming((n) => n && { ...n, busy: false, error: errorText(e) })
    } finally {
      creating.current = false
    }
  }

  async function upload(folder: string, files: File[], overwrite = false) {
    setNotice(null)
    const big = files.find((f) => f.size > MAX_FILE)
    const tooMany = files.length > MAX_FILES
    const tooLarge = files.reduce((n, f) => n + f.size, 0) > MAX_TOTAL
    if (big || tooMany || tooLarge) {
      return setNotice({
        severity: 'error',
        text: big ? `${big.name} is larger than 5 MB, the most one file can be.` : tooMany ? `Upload at most ${MAX_FILES} files at a time.` : 'Upload at most 25 MB at a time.',
      })
    }
    if (!files.length) return
    const form = new FormData()
    form.append('folder', folder)
    form.append('overwrite', String(overwrite))
    for (const f of files) form.append('files', f, f.name)
    setUploading(`Uploading ${plural(files.length, 'file')}…`)
    try {
      const { written } = await api<{ written: string[] }>(`/api/agents/${agentId}/files`, { method: 'POST', body: form })
      if (folder) expand([...parents(folder), folder])
      setNotice({ severity: 'success', text: `Uploaded ${plural(written.length, 'file')}${folder ? ` to ${folder}` : ''}.` })
      onRefresh()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'files_exist' && Array.isArray(e.details?.paths)) {
        setConflict({ folder, files, taken: e.details.paths as string[] })
      } else {
        // A failure part way may have written some files: the tree shows which.
        if (e instanceof ApiError && e.details?.written) onRefresh()
        setNotice({ severity: 'error', text: `The upload failed. ${errorText(e)}` })
      }
    } finally {
      setUploading('')
    }
  }

  function dropFolder(e: DragEvent): string {
    const row = (e.target as HTMLElement).closest<HTMLElement>('[data-folder]')
    return row?.dataset.folder ?? ''
  }

  function onDrop(e: DragEvent) {
    e.preventDefault()
    const folder = dropFolder(e)
    setDropOn(null)
    const items = [...e.dataTransfer.items]
    if (items.some((i) => i.webkitGetAsEntry?.()?.isDirectory)) {
      return setNotice({ severity: 'error', text: 'Folders cannot be uploaded yet. Open the folder and drop the files inside it.' })
    }
    void upload(folder, [...e.dataTransfer.files])
  }

  const nameRow = naming && (
    <NameRow
      key="naming"
      naming={naming}
      depth={naming.folder ? naming.folder.split('/').length : 0}
      onChange={(name) => setNaming({ ...naming, name, error: name.trim() ? nameProblem(name, entries, naming.folder) ?? '' : '' })}
      onSubmit={() => finishNaming(true)}
      onBlur={() => finishNaming(false)}
      onCancel={() => setNaming(null)}
    />
  )
  // The name box sits first inside its folder, where the new entry will appear.
  const at = naming ? (naming.folder ? rows.findIndex((r) => r.path === naming.folder) + 1 : 0) : -1

  return (
    <Box component="aside" aria-label="Files" sx={{ display: 'flex', flexDirection: 'column', minHeight: 0, flex: 1 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.25, py: 1, pl: 2, pr: 0.5, borderBottom: 1, borderColor: 'divider' }}>
        <Typography sx={{ flexGrow: 1, fontSize: 12, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'text.secondary' }}>
          Explorer
        </Typography>
        <HeaderButton label="New file" onClick={() => startNaming('file', target)}><NoteAddOutlined fontSize="small" /></HeaderButton>
        <HeaderButton label="New folder" onClick={() => startNaming('folder', target)}><CreateNewFolderOutlined fontSize="small" /></HeaderButton>
        <HeaderButton label="Upload files" onClick={() => picker.current?.click()} disabled={!!uploading}><FileUploadOutlined fontSize="small" /></HeaderButton>
        <HeaderButton label="Refresh" onClick={onRefresh}><Refresh fontSize="small" /></HeaderButton>
        <input
          ref={picker}
          type="file"
          multiple
          hidden
          aria-hidden
          tabIndex={-1}
          onChange={(e) => {
            const files = [...(e.target.files ?? [])]
            e.target.value = ''
            void upload(target, files)
          }}
        />
      </Box>
      {(uploading || notice) && (
        <Box role="status" sx={{ px: 1, pt: 1 }}>
          {uploading ? (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1, fontSize: 12, color: 'text.secondary' }}>
              <CircularProgress size={12} /> {uploading}
            </Box>
          ) : notice && (
            <Alert severity={notice.severity} onClose={() => setNotice(null)} sx={{ py: 0, fontSize: 12, '& .MuiAlert-icon': { fontSize: 16 } }}>
              {notice.text}
            </Alert>
          )}
        </Box>
      )}
      <Box
        component="ul"
        aria-label="Workspace files. Drop files here to upload them."
        onDragOver={(e) => {
          if (!e.dataTransfer.types.includes('Files')) return
          e.preventDefault()
          e.dataTransfer.dropEffect = 'copy'
          setDropOn(dropFolder(e))
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node)) setDropOn(null)
        }}
        onDrop={onDrop}
        sx={{
          listStyle: 'none', m: 0, py: 1, px: 0, overflow: 'auto', flexGrow: 1, fontSize: 13,
          outline: dropOn === '' ? '2px dashed' : 'none', outlineColor: 'primary.main', outlineOffset: -4,
        }}
      >
        {at === 0 && nameRow}
        {rows.map((row, i) => (
          <TreeRow
            key={row.path}
            row={row}
            open={expanded.has(row.path)}
            current={(selected?.path ?? active) === row.path}
            dropping={row.dir && dropOn === row.path}
            after={at === i + 1 ? nameRow : null}
            onClick={() => {
              setSelected({ path: row.path, dir: row.dir })
              if (row.dir) toggle(row.path)
              else onOpen(row.path)
            }}
            onNew={(kind) => startNaming(kind, row.path)}
          />
        ))}
        {tree?.truncated && (
          <Typography component="li" color="text.secondary" sx={{ px: 2, py: 1, fontSize: 12 }}>
            Only the first {tree.entries.length} entries are shown.
          </Typography>
        )}
        {tree && tree.entries.length === 0 && !naming && (
          <Typography component="li" color="text.secondary" sx={{ px: 2, py: 1, fontSize: 12 }}>No files yet. Drop files here, or use the buttons above.</Typography>
        )}
      </Box>
      {storage && <StorageLine storage={storage} />}
      {conflict && (
        <ReplaceDialog
          conflict={conflict}
          onClose={() => setConflict(null)}
          onReplace={() => (setConflict(null), void upload(conflict.folder, conflict.files, true))}
          onSkip={() => {
            setConflict(null)
            const rest = conflict.files.filter((f) => !conflict.taken.includes(join(conflict.folder, f.name)))
            if (rest.length) void upload(conflict.folder, rest)
            else setNotice({ severity: 'success', text: 'Nothing uploaded: every file was already there.' })
          }}
        />
      )}
    </Box>
  )
}

function HeaderButton({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return (
    <Tooltip title={label}>
      <span>
        <IconButton size="small" aria-label={label} onClick={onClick} disabled={disabled}>{children}</IconButton>
      </span>
    </Tooltip>
  )
}

type TreeRowProps = {
  row: Row
  open: boolean
  current: boolean
  dropping: boolean
  after: ReactNode
  onClick: () => void
  onNew: (kind: NewKind) => void
}

function TreeRow({ row, open, current, dropping, after, onClick, onNew }: TreeRowProps) {
  return (
    <>
      <Box
        component="li"
        data-folder={row.dir ? row.path : undefined}
        sx={{ position: 'relative', '&:hover .actions, &:focus-within .actions': { opacity: 1 } }}
      >
        <ButtonBase
          onClick={onClick}
          aria-expanded={row.dir ? open : undefined}
          sx={{
            width: '100%', justifyContent: 'flex-start', gap: 0.75, py: 0.5, pr: row.dir ? 7 : 1.5, pl: `${12 + row.depth * 14}px`,
            fontSize: 13, color: 'text.primary', bgcolor: dropping || current ? 'var(--accentSoft)' : 'transparent',
            outline: dropping ? '1px solid' : 'none', outlineColor: 'primary.main', outlineOffset: -1,
            '&:hover': { bgcolor: current || dropping ? 'var(--accentSoft)' : 'var(--raised)' },
          }}
        >
          {row.dir ? (
            open ? <ExpandMore sx={{ fontSize: 16, color: 'text.secondary' }} /> : <ChevronRight sx={{ fontSize: 16, color: 'text.secondary' }} />
          ) : (
            <InsertDriveFileOutlined sx={{ fontSize: 14, color: 'text.secondary', mx: '1px' }} />
          )}
          <Box component="span" sx={{ flexGrow: 1, textAlign: 'left', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row.name}</Box>
          <Box component="span" sx={{ fontFamily: MONO, fontSize: 11, fontWeight: 500, color: 'warning.main' }}>{row.status}</Box>
        </ButtonBase>
        {row.dir && (
          <Box className="actions" sx={{ position: 'absolute', right: 4, top: 0, bottom: 0, display: 'flex', alignItems: 'center', opacity: { xs: 1, md: 0 } }}>
            <Tooltip title="New file here">
              <IconButton size="small" aria-label={`New file in ${row.path}`} onClick={() => onNew('file')} sx={{ p: 0.25 }}>
                <NoteAddOutlined sx={{ fontSize: 16 }} />
              </IconButton>
            </Tooltip>
            <Tooltip title="New folder here">
              <IconButton size="small" aria-label={`New folder in ${row.path}`} onClick={() => onNew('folder')} sx={{ p: 0.25 }}>
                <CreateNewFolderOutlined sx={{ fontSize: 16 }} />
              </IconButton>
            </Tooltip>
          </Box>
        )}
      </Box>
      {after}
    </>
  )
}

type NameRowProps = {
  naming: Naming
  depth: number
  onChange: (name: string) => void
  onSubmit: () => void
  onBlur: () => void
  onCancel: () => void
}

function NameRow({ naming, depth, onChange, onSubmit, onBlur, onCancel }: NameRowProps) {
  const label = naming.kind === 'file' ? 'New file name' : 'New folder name'
  return (
    <Box component="li" sx={{ pl: `${12 + depth * 14}px`, pr: 1, py: 0.25 }}>
      <Box
        component="form"
        onSubmit={(e) => {
          e.preventDefault()
          onSubmit()
        }}
        sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}
      >
        {naming.kind === 'file' ? <InsertDriveFileOutlined sx={{ fontSize: 14, color: 'text.secondary', mx: '1px' }} /> : <FolderOutlined sx={{ fontSize: 16, color: 'text.secondary' }} />}
        <InputBase
          autoFocus
          fullWidth
          value={naming.name}
          disabled={naming.busy}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.stopPropagation()
              onCancel()
            }
          }}
          onBlur={onBlur}
          inputProps={{ 'aria-label': label, 'aria-invalid': !!naming.error, 'aria-describedby': naming.error ? 'name-problem' : undefined, spellCheck: false, autoComplete: 'off' }}
          sx={{ fontFamily: MONO, fontSize: 13, px: 0.75, border: 1, borderColor: naming.error ? 'error.main' : 'primary.main', borderRadius: '4px' }}
        />
      </Box>
      {naming.error && (
        <Typography id="name-problem" role="alert" sx={{ fontSize: 12, color: 'error.main', pl: 2.75, pt: 0.25 }}>{naming.error}</Typography>
      )}
    </Box>
  )
}

function ReplaceDialog({ conflict, onClose, onReplace, onSkip }: { conflict: Conflict; onClose: () => void; onReplace: () => void; onSkip: () => void }) {
  const { taken, files } = conflict
  const all = taken.length === files.length
  return (
    <Dialog open onClose={onClose} aria-labelledby="replace-title">
      <DialogTitle id="replace-title">{taken.length === 1 ? `Replace ${taken[0]}?` : `Replace ${taken.length} files?`}</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
        <Typography color="text.secondary">
          {taken.length === 1 ? 'A file with this name is already in the workspace.' : 'These files are already in the workspace:'} Replacing overwrites it with the uploaded copy.
        </Typography>
        {taken.length > 1 && (
          <Box component="ul" sx={{ m: 0, pl: 2.5, maxHeight: 160, overflow: 'auto', fontFamily: MONO, fontSize: 13 }}>
            {taken.map((p) => <li key={p}>{p}</li>)}
          </Box>
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose}>Cancel</Button>
        {!all && <Button onClick={onSkip}>Skip {taken.length === 1 ? 'it' : 'those'}</Button>}
        <Button variant="contained" onClick={onReplace}>Replace</Button>
      </DialogActions>
    </Dialog>
  )
}

const LEVEL_COLOR = { ok: 'text.secondary', warning: 'warning.main', error: 'error.main' } as const

function StorageLine({ storage }: { storage: Storage }) {
  const level = storageLevel(storage.used_bytes, storage.limit_bytes)
  return (
    <Box sx={{ px: 2, py: 1, borderTop: 1, borderColor: 'divider', fontSize: 12, color: LEVEL_COLOR[level] }}>
      <Box component="span" sx={{ fontFamily: MONO }}>{bytes(storage.used_bytes)}</Box> of {bytes(storage.limit_bytes)} used
      {level === 'error' && <Box sx={{ mt: 0.25 }}>Full: delete files, or ask the agent to, before it can write again.</Box>}
    </Box>
  )
}
