import ChevronRight from '@mui/icons-material/ChevronRight'
import ExpandMore from '@mui/icons-material/ExpandMore'
import InsertDriveFileOutlined from '@mui/icons-material/InsertDriveFileOutlined'
import NoteAddOutlined from '@mui/icons-material/NoteAddOutlined'
import Refresh from '@mui/icons-material/Refresh'
import { Box, ButtonBase, IconButton, InputBase, Tooltip, Typography } from '@mui/material'
import { useMemo, useState } from 'react'
import type { Storage, Tree } from '../api/types'
import { bytes, storageLevel } from '../format'
import { MONO } from '../theme'
import { buildRows } from './tree'

type Props = {
  tree: Tree | null
  letters: Map<string, string>
  active: string | null
  onOpen: (path: string) => void
  onRefresh: () => void
  onCreate: (path: string) => void
  storage: Storage | null
}

export function Explorer({ tree, letters, active, onOpen, onRefresh, onCreate, storage }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [naming, setNaming] = useState<string | null>(null)
  const rows = useMemo(() => buildRows(tree?.entries ?? [], letters, expanded), [tree, letters, expanded])

  const toggle = (path: string) =>
    setExpanded((all) => {
      const next = new Set(all)
      if (!next.delete(path)) next.add(path)
      return next
    })

  return (
    <Box component="aside" aria-label="Files" sx={{ display: 'flex', flexDirection: 'column', minHeight: 0, flex: 1 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, py: 1.25, pl: 2, pr: 1, borderBottom: 1, borderColor: 'divider' }}>
        <Typography sx={{ flexGrow: 1, fontSize: 12, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'text.secondary' }}>
          Explorer
        </Typography>
        <Tooltip title="New file">
          <IconButton size="small" aria-label="New file" onClick={() => setNaming('')}>
            <NoteAddOutlined fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title="Refresh">
          <IconButton size="small" aria-label="Refresh" onClick={onRefresh}>
            <Refresh fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>
      {naming !== null && (
        <Box
          component="form"
          sx={{ px: 1.5, py: 1, borderBottom: 1, borderColor: 'divider' }}
          onSubmit={(e) => {
            e.preventDefault()
            if (naming.trim()) onCreate(naming.trim())
            setNaming(null)
          }}
        >
          <InputBase
            autoFocus
            fullWidth
            value={naming}
            placeholder="path/to/file.txt"
            onChange={(e) => setNaming(e.target.value)}
            onKeyDown={(e) => e.key === 'Escape' && setNaming(null)}
            onBlur={() => setNaming(null)}
            inputProps={{ 'aria-label': 'New file path' }}
            sx={{ fontFamily: MONO, fontSize: 13, px: 1, border: 1, borderColor: 'primary.main', borderRadius: '6px' }}
          />
        </Box>
      )}
      <Box component="ul" sx={{ listStyle: 'none', m: 0, py: 1, px: 0, overflow: 'auto', flexGrow: 1, fontSize: 13 }}>
        {rows.map((row) => (
          <li key={row.path}>
            <ButtonBase
              onClick={() => (row.dir ? toggle(row.path) : onOpen(row.path))}
              aria-expanded={row.dir ? expanded.has(row.path) : undefined}
              sx={{
                width: '100%', justifyContent: 'flex-start', gap: 0.75, py: 0.5, pr: 1.5, pl: `${12 + row.depth * 14}px`,
                fontSize: 13, color: 'text.primary', bgcolor: active === row.path ? 'var(--accentSoft)' : 'transparent',
                '&:hover': { bgcolor: active === row.path ? 'var(--accentSoft)' : 'var(--raised)' },
              }}
            >
              {row.dir ? (
                expanded.has(row.path) ? <ExpandMore sx={{ fontSize: 16, color: 'text.secondary' }} /> : <ChevronRight sx={{ fontSize: 16, color: 'text.secondary' }} />
              ) : (
                <InsertDriveFileOutlined sx={{ fontSize: 14, color: 'text.secondary', mx: '1px' }} />
              )}
              <Box component="span" sx={{ flexGrow: 1, textAlign: 'left', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row.name}</Box>
              <Box component="span" sx={{ fontFamily: MONO, fontSize: 11, fontWeight: 500, color: 'warning.main' }}>{row.status}</Box>
            </ButtonBase>
          </li>
        ))}
        {tree?.truncated && (
          <Typography component="li" color="text.secondary" sx={{ px: 2, py: 1, fontSize: 12 }}>
            Only the first {tree.entries.length} entries are shown.
          </Typography>
        )}
        {tree && tree.entries.length === 0 && (
          <Typography component="li" color="text.secondary" sx={{ px: 2, py: 1, fontSize: 12 }}>No files yet.</Typography>
        )}
      </Box>
      {storage && <StorageLine storage={storage} />}
    </Box>
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
