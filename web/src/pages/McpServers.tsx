import Add from '@mui/icons-material/Add'
import CableOutlined from '@mui/icons-material/CableOutlined'
import Close from '@mui/icons-material/Close'
import DeleteOutlined from '@mui/icons-material/DeleteOutlined'
import ExpandMore from '@mui/icons-material/ExpandMore'
import {
  Alert, Box, Button, Checkbox, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel,
  IconButton, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from '@mui/material'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { api, errorText } from '../api/client'
import type { McpServer, McpTool } from '../api/types'
import { ago } from '../format'
import { MONO } from '../theme'

const card = { border: 1, borderColor: 'divider', borderRadius: '12px', bgcolor: 'background.paper' }
const chip = { px: 1, py: '1px', borderRadius: 999, bgcolor: 'var(--raised)', color: 'text.secondary', fontSize: 12, flexShrink: 0 }
const mono = { fontFamily: MONO, fontSize: 13 }
const noFill = { autoComplete: 'off', 'data-1p-ignore': true, 'data-lpignore': 'true', 'data-form-type': 'other' }

/** Leaving for the provider's sign-in page; a seam so tests can see where it would go. */
export const leave = { to: (url: string) => window.location.assign(url) }

// What the OAuth callback's ?error= codes mean to the user. The provider's own text is never shown.
const CONNECT_ERRORS: Record<string, string> = {
  oauth_denied: 'The sign-in was declined or cancelled at the provider. Connect again to retry.',
  oauth_state_invalid: 'This sign-in link expired or was already used. Connect again.',
  oauth_not_needed: 'The server answered without asking to sign in. Delete it and add it again with sign-in set to none or headers.',
}
const CONNECT_FAILED = 'The server could not be connected. Connect again; if it keeps failing, check that the address is right and the server is up.'

/** The command line as a shell would show it, so the user sees exactly what will run. */
export function commandLine(command: string, args: string[]) {
  const quote = (a: string) => (/^[\w@%+=:,./-]+$/.test(a) ? a : `'${a.replace(/'/g, `'\\''`)}'`)
  return [command, ...args].map(quote).join(' ')
}

const where = (s: McpServer) => (s.kind === 'remote' ? s.url ?? '' : commandLine(s.command ?? '', s.args ?? []))
const authText = (s: McpServer) =>
  s.kind === 'local'
    ? s.env_names.length ? `Variables ${s.env_names.join(', ')}` : 'No variables'
    : s.auth === 'oauth' ? (s.preregistered ? 'OAuth with your client' : 'OAuth') : s.auth === 'headers' ? `Headers ${s.header_names.join(', ')}` : 'No sign-in'

function ToolList({ tools, label }: { tools: McpTool[]; label: string }) {
  return (
    <Box component="ul" aria-label={label} sx={{ listStyle: 'none', m: 0, p: 0, display: 'flex', flexDirection: 'column', gap: 0.75 }}>
      {tools.map((t) => (
        <Box component="li" key={t.name} sx={{ fontSize: 13, minWidth: 0 }}>
          <Box component="span" sx={{ fontFamily: MONO, fontSize: 12 }}>{t.name}</Box>
          {t.description && (
            <Typography color="text.secondary" sx={{ fontSize: 12, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }} title={t.description}>
              {t.description}
            </Typography>
          )}
        </Box>
      ))}
    </Box>
  )
}

function Review({ server, onClose, onAccepted }: { server: McpServer; onClose: () => void; onAccepted: (s: McpServer) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const now = server.pending_tools ?? []
  const before = new Map(server.tools.map((t) => [t.name, t]))
  const added = now.filter((t) => !before.has(t.name))
  const changed = now.filter((t) => before.has(t.name) && before.get(t.name)!.description !== t.description)
  const removed = server.tools.filter((t) => !now.some((n) => n.name === t.name))

  async function accept() {
    setBusy(true)
    setError('')
    try {
      onAccepted(await api<McpServer>(`/api/mcp-servers/${server.id}/tools/review`, { method: 'POST', body: { hash: server.pending_hash } }))
    } catch (e) {
      setError(errorText(e))
      setBusy(false)
    }
  }

  const section = (title: string, tools: McpTool[]) =>
    tools.length > 0 && (
      <Box>
        <Typography component="h3" sx={{ fontSize: 13, fontWeight: 600, mb: 0.75 }}>{title}</Typography>
        <ToolList tools={tools} label={title} />
      </Box>
    )

  return (
    <Dialog open onClose={busy ? undefined : onClose} fullWidth maxWidth="sm">
      <DialogTitle>Review {server.name}'s tools</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <Typography color="text.secondary" sx={{ fontSize: 14 }}>
          The server's tools changed since you last saw them, so agents stopped using it. A tool's description tells the agent what it does, so check that nothing reads like an instruction you would not give.
        </Typography>
        {section('New tools', added)}
        {section('Changed descriptions', changed)}
        {section('Removed tools', removed)}
        {added.length + changed.length + removed.length === 0 && <Typography sx={{ fontSize: 14 }}>Only the tools' settings changed.</Typography>}
        {error && <Alert severity="error">{error}</Alert>}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" onClick={accept} disabled={busy}>{busy ? 'Accepting…' : 'Accept tools'}</Button>
      </DialogActions>
    </Dialog>
  )
}

type Row = { name: string; value: string }

/** Name and value rows for headers or environment variables. Values are password fields: they go
 *  to the server once and are never shown again. */
function SecretRows({ label, rows, onChange, placeholder }: { label: string; rows: Row[]; onChange: (rows: Row[]) => void; placeholder: string }) {
  const set = (i: number, change: Partial<Row>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...change } : r)))
  return (
    <Box role="group" aria-label={label} sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      {rows.map((r, i) => (
        <Box key={i} sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
          <TextField label="Name" size="small" value={r.name} onChange={(e) => set(i, { name: e.target.value })} placeholder={placeholder} required sx={{ flex: 1 }} slotProps={{ htmlInput: { maxLength: 100, ...noFill, style: mono } }} />
          <TextField label="Value" size="small" type="password" value={r.value} onChange={(e) => set(i, { value: e.target.value })} required sx={{ flex: 1 }} slotProps={{ htmlInput: { maxLength: 4000, ...noFill, autoComplete: 'new-password', style: mono } }} />
          <IconButton aria-label={`Remove ${r.name || 'row'}`} size="small" onClick={() => onChange(rows.filter((_, j) => j !== i))}><Close fontSize="small" /></IconButton>
        </Box>
      ))}
      <Button size="small" startIcon={<Add />} onClick={() => onChange([...rows, { name: '', value: '' }])} sx={{ alignSelf: 'flex-start' }}>
        Add {label.toLowerCase().replace(/s$/, '')}
      </Button>
    </Box>
  )
}

const toObject = (rows: Row[]) => Object.fromEntries(rows.map((r) => [r.name.trim(), r.value]))

function AddServer({ onClose, onAdded }: { onClose: () => void; onAdded: (s: McpServer) => void }) {
  const [kind, setKind] = useState<'remote' | 'local'>('remote')
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [auth, setAuth] = useState<'none' | 'headers' | 'oauth'>('none')
  const [headers, setHeaders] = useState<Row[]>([{ name: 'Authorization', value: '' }])
  const [ownClient, setOwnClient] = useState(false)
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [command, setCommand] = useState('')
  const [args, setArgs] = useState('')
  const [env, setEnv] = useState<Row[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const argList = args.split('\n').filter((a) => a !== '')

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    const body = kind === 'remote'
      ? {
          name, kind, url: url.trim(), auth,
          headers: auth === 'headers' ? toObject(headers) : undefined,
          client_id: auth === 'oauth' && ownClient ? clientId.trim() : undefined,
          client_secret: auth === 'oauth' && ownClient && clientSecret ? clientSecret : undefined,
        }
      : { name, kind, command: command.trim(), args: argList, env: env.length ? toObject(env) : undefined }
    try {
      onAdded(await api<McpServer>('/api/mcp-servers', { method: 'POST', body }))
    } catch (err) {
      setError(errorText(err))
      setBusy(false)
    }
  }

  return (
    <Dialog open onClose={busy ? undefined : onClose} fullWidth maxWidth="sm" slotProps={{ paper: { component: 'form', onSubmit: submit, autoComplete: 'off' } as object }}>
      <DialogTitle>Add an MCP server</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2.5, pt: '8px !important' }}>
        <ToggleButtonGroup exclusive size="small" value={kind} onChange={(_, k) => k && setKind(k)} aria-label="Where it runs">
          <ToggleButton value="remote" sx={{ textTransform: 'none' }}>Remote, at a URL</ToggleButton>
          <ToggleButton value="local" sx={{ textTransform: 'none' }}>Local, a command</ToggleButton>
        </ToggleButtonGroup>
        <TextField
          label="Name"
          size="small"
          required
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value.toLowerCase())}
          placeholder="linear"
          helperText="Lower case letters, digits and underscores. The agent sees its tools as name_tool."
          slotProps={{ htmlInput: { maxLength: 20, pattern: '[a-z][a-z0-9_]*', ...noFill, style: mono } }}
        />
        {kind === 'remote' ? (
          <>
            <TextField label="URL" size="small" required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://mcp.example.com/mcp" helperText="An https address on the public internet." slotProps={{ htmlInput: { maxLength: 500, ...noFill, style: mono } }} />
            <Box>
              <Typography id="auth-label" sx={{ fontSize: 13, fontWeight: 500, mb: 1 }}>Sign-in</Typography>
              <ToggleButtonGroup exclusive size="small" value={auth} onChange={(_, a) => a && setAuth(a)} aria-labelledby="auth-label">
                <ToggleButton value="none" sx={{ textTransform: 'none' }}>None</ToggleButton>
                <ToggleButton value="headers" sx={{ textTransform: 'none' }}>Headers</ToggleButton>
                <ToggleButton value="oauth" sx={{ textTransform: 'none' }}>OAuth</ToggleButton>
              </ToggleButtonGroup>
            </Box>
            {auth === 'headers' && <SecretRows label="Headers" rows={headers} onChange={setHeaders} placeholder="Authorization" />}
            {auth === 'oauth' && (
              <>
                <Typography color="text.secondary" sx={{ fontSize: 13 }}>After adding it, connect it: you sign in at the provider and come back here.</Typography>
                <FormControlLabel control={<Checkbox checked={ownClient} onChange={(e) => setOwnClient(e.target.checked)} />} label="I have a client id from the provider" />
                {ownClient && (
                  <>
                    <TextField label="Client id" size="small" required value={clientId} onChange={(e) => setClientId(e.target.value)} slotProps={{ htmlInput: { maxLength: 500, ...noFill, style: mono } }} />
                    <TextField label="Client secret" size="small" type="password" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} helperText="Only if the provider gave you one." slotProps={{ htmlInput: { maxLength: 4000, ...noFill, autoComplete: 'new-password', style: mono } }} />
                  </>
                )}
              </>
            )}
          </>
        ) : (
          <>
            <TextField label="Command" size="small" required value={command} onChange={(e) => setCommand(e.target.value)} placeholder="npx" slotProps={{ htmlInput: { maxLength: 500, ...noFill, style: mono } }} />
            <TextField label="Arguments" size="small" multiline minRows={2} value={args} onChange={(e) => setArgs(e.target.value)} placeholder={'-y\n@modelcontextprotocol/server-everything'} helperText="One per line, passed as they are: no shell expands them." slotProps={{ htmlInput: { ...noFill, style: mono } }} />
            <SecretRows label="Environment variables" rows={env} onChange={setEnv} placeholder="API_KEY" />
            {command.trim() && (
              <Box>
                <Typography sx={{ fontSize: 13, fontWeight: 500, mb: 0.5 }}>Runs as</Typography>
                <Box component="code" aria-label="Command line" sx={{ display: 'block', p: 1, borderRadius: '6px', bgcolor: 'var(--raised)', ...mono, overflowWrap: 'anywhere' }}>{commandLine(command.trim(), argList)}</Box>
              </Box>
            )}
            <Alert severity="warning">
              It runs in each workspace that uses it, with the same access as the agent: it can read and change the workspace's files and reach the internet. Add only servers you trust.
            </Alert>
            <Alert severity="info">The agent can read these environment variables in the workspace, so use keys you would give the agent itself.</Alert>
          </>
        )}
        {error && <Alert severity="error">{error}</Alert>}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2.5 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? (kind === 'remote' ? 'Connecting…' : 'Adding…') : 'Add server'}</Button>
      </DialogActions>
    </Dialog>
  )
}

function ReplaceSecrets({ server, onClose, onSaved }: { server: McpServer; onClose: () => void; onSaved: (s: McpServer) => void }) {
  const local = server.kind === 'local'
  const [rows, setRows] = useState<Row[]>((local ? server.env_names : server.header_names).map((name) => ({ name, value: '' })))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      onSaved(await api<McpServer>(`/api/mcp-servers/${server.id}`, { method: 'PATCH', body: local ? { env: toObject(rows) } : { headers: toObject(rows) } }))
    } catch (err) {
      setError(errorText(err))
      setBusy(false)
    }
  }

  return (
    <Dialog open onClose={busy ? undefined : onClose} fullWidth maxWidth="sm" slotProps={{ paper: { component: 'form', onSubmit: submit, autoComplete: 'off' } as object }}>
      <DialogTitle>Replace {local ? 'variables' : 'headers'} for {server.name}</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: '8px !important' }}>
        <Typography color="text.secondary" sx={{ fontSize: 14 }}>The stored values are never shown. These rows replace all of them.</Typography>
        <SecretRows label={local ? 'Environment variables' : 'Headers'} rows={rows} onChange={setRows} placeholder={local ? 'API_KEY' : 'Authorization'} />
        {error && <Alert severity="error">{error}</Alert>}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2.5 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? 'Saving…' : 'Save'}</Button>
      </DialogActions>
    </Dialog>
  )
}

const STATUS: Record<McpServer['status'], { text: string; action?: string }> = {
  ok: { text: 'Ready' },
  needs_auth: { text: 'Not connected', action: 'Connect' },
  needs_scope: { text: 'Needs more access', action: 'Reconnect' },
  tools_changed: { text: 'Tools changed', action: 'Review tools' },
}

function ServerRow({ server, startOpen, onAction, onReplace, onDelete }: {
  server: McpServer; startOpen: boolean; onAction: () => void; onReplace: () => void; onDelete: () => void
}) {
  const [open, setOpen] = useState(startOpen)
  const status = STATUS[server.status]
  const secrets = server.kind === 'local' || server.auth === 'headers'
  return (
    <Box component="li" sx={{ '& + &': { borderTop: 1, borderColor: 'divider' } }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, px: 2, py: 1.5, flexWrap: 'wrap' }}>
        <Box sx={{ flex: '1 1 240px', minWidth: 0 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
            <Typography component="h3" noWrap sx={{ fontSize: 14, fontWeight: 600, fontFamily: MONO }}>{server.name}</Typography>
            <Box component="span" sx={chip}>{server.kind === 'remote' ? 'Remote' : 'Local'}</Box>
            <Box component="span" sx={{ ...chip, ...(server.status !== 'ok' && { bgcolor: 'var(--accentSoft)', color: 'text.primary' }) }}>{status.text}</Box>
          </Box>
          <Typography color="text.secondary" noWrap title={where(server)} sx={{ fontSize: 12, mt: 0.25 }}>
            <Box component="span" sx={{ fontFamily: MONO }}>{where(server)}</Box>
          </Typography>
          <Typography color="text.secondary" noWrap sx={{ fontSize: 12 }}>{authText(server)} · Added {ago(server.created_at)}</Typography>
        </Box>
        {status.action && <Button size="small" variant="contained" onClick={onAction}>{status.action}</Button>}
        <Button size="small" aria-expanded={open} onClick={() => setOpen(!open)} endIcon={<ExpandMore sx={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .15s' }} />} sx={{ fontWeight: 400, color: 'text.secondary' }}>
          {server.tools.length === 1 ? '1 tool' : `${server.tools.length} tools`}
        </Button>
        {secrets && <Button size="small" onClick={onReplace} sx={{ fontWeight: 400, color: 'text.secondary' }}>Replace {server.kind === 'local' ? 'variables' : 'headers'}</Button>}
        <Tooltip title="Delete server">
          <IconButton aria-label={`Delete ${server.name}`} onClick={onDelete} size="small"><DeleteOutlined fontSize="small" /></IconButton>
        </Tooltip>
      </Box>
      {open && (
        <Box sx={{ px: 2, pb: 1.5 }}>
          {server.tools.length ? (
            <ToolList tools={server.tools} label={`Tools of ${server.name}`} />
          ) : (
            <Typography color="text.secondary" sx={{ fontSize: 13 }}>
              {server.kind === 'local' ? 'Its tools are listed the first time a workspace starts it.' : server.status === 'needs_auth' ? 'Its tools are listed once it is connected.' : 'This server offers no tools.'}
            </Typography>
          )}
        </Box>
      )}
    </Box>
  )
}

export function McpServers() {
  const [servers, setServers] = useState<McpServer[] | null>(null)
  const [loadError, setLoadError] = useState('')
  const [error, setError] = useState('')
  const [query, setQuery] = useSearchParams()
  // Read once: the callback's result, then the address is cleaned so a reload does not repeat it.
  const [arrival] = useState(() => ({ connected: query.get('connected'), error: query.get('error') }))
  const [adding, setAdding] = useState(false)
  const [added, setAdded] = useState<string | null>(null)
  const [reviewing, setReviewing] = useState<McpServer | null>(null)
  const [replacing, setReplacing] = useState<McpServer | null>(null)
  const [deleting, setDeleting] = useState<McpServer | null>(null)
  const [connecting, setConnecting] = useState('')

  function load() {
    setLoadError('')
    api<McpServer[]>('/api/mcp-servers').then(setServers, (e) => setLoadError(errorText(e)))
  }

  useEffect(() => {
    load()
    if (arrival.connected || arrival.error) setQuery({}, { replace: true })
  }, [])

  const put = (s: McpServer) => setServers((all) => all?.map((x) => (x.id === s.id ? s : x)) ?? null)

  async function connect(s: McpServer) {
    setConnecting(s.name)
    setError('')
    try {
      const { authorize_url } = await api<{ authorize_url: string }>(`/api/mcp-servers/${s.id}/oauth`, { method: 'POST' })
      // Only ever a web page: a javascript: address would run in this page.
      if (!/^https?:\/\//i.test(authorize_url)) throw new Error('The server gave a sign-in address that is not a web page, so Echo did not open it.')
      leave.to(authorize_url)
    } catch (e) {
      setError(`${s.name} could not start connecting. ${errorText(e)}`)
      setConnecting('')
    }
  }

  async function remove(s: McpServer) {
    setDeleting(null)
    try {
      await api(`/api/mcp-servers/${s.id}`, { method: 'DELETE' })
      setServers((all) => all?.filter((x) => x.id !== s.id) ?? null)
    } catch (e) {
      setError(`${s.name} was not deleted. ${errorText(e)}`)
    }
  }

  const connectedName = arrival.connected && servers?.find((s) => s.id === arrival.connected)?.name
  const addButton = <Button variant="contained" startIcon={<Add />} onClick={() => setAdding(true)} sx={{ flexShrink: 0 }}>Add server</Button>

  return (
    <Box sx={{ minHeight: '100%', display: 'flex', flexDirection: 'column' }}>
      <Box component="main" sx={{ width: '100%', maxWidth: 760, mx: 'auto', px: 2, py: { xs: 4, md: 6 }, display: 'flex', flexDirection: 'column', gap: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 2, flexWrap: 'wrap' }}>
          <Box sx={{ flex: '1 1 320px' }}>
            <Typography component="h1" sx={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.01em' }}>Connectors</Typography>
            <Typography color="text.secondary" sx={{ fontSize: 14, mt: 0.5 }}>
              MCP servers give your agents tools from other services. Turn them on per workspace with /mcp; the agent asks before calling them unless the workspace is on yolo.
            </Typography>
          </Box>
          {servers && servers.length > 0 && addButton}
        </Box>
        {connectedName && <Alert severity="success">{connectedName} is connected.</Alert>}
        {arrival.connected && servers && !connectedName && <Alert severity="success">The server is connected.</Alert>}
        {arrival.error && <Alert severity="error">{CONNECT_ERRORS[arrival.error] ?? CONNECT_FAILED}</Alert>}
        {connecting && <Alert severity="info">Opening {connecting}'s sign-in…</Alert>}
        {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}
        {loadError ? (
          <Alert severity="error" action={<Button size="small" onClick={load}>Retry</Button>}>Your servers could not be loaded. {loadError}</Alert>
        ) : servers === null ? (
          <Box role="status" aria-label="Loading servers" sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress size={20} /></Box>
        ) : servers.length === 0 ? (
          <Box sx={{ ...card, p: 4, display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 1.5 }}>
            <CableOutlined sx={{ fontSize: 28, color: 'text.secondary' }} />
            <Box>
              <Typography sx={{ fontWeight: 600 }}>No servers yet</Typography>
              <Typography color="text.secondary" sx={{ fontSize: 14 }}>Add a server by its URL, or a command that runs it in the workspace.</Typography>
            </Box>
            {addButton}
          </Box>
        ) : (
          <Box component="section" aria-labelledby="your-servers" sx={card}>
            <Typography id="your-servers" component="h2" sx={{ fontSize: 13, fontWeight: 600, color: 'text.secondary', px: 2, pt: 1.5, pb: 0.5 }}>
              {servers.length === 1 ? '1 server' : `${servers.length} servers`}
            </Typography>
            <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0 }}>
              {servers.map((s) => (
                <ServerRow
                  key={s.id}
                  server={s}
                  startOpen={s.id === added}
                  onAction={() => (s.status === 'tools_changed' ? setReviewing(s) : connect(s))}
                  onReplace={() => setReplacing(s)}
                  onDelete={() => setDeleting(s)}
                />
              ))}
            </Box>
          </Box>
        )}
      </Box>
      {adding && (
        <AddServer
          onClose={() => setAdding(false)}
          onAdded={(s) => {
            setServers((all) => [s, ...(all ?? [])])
            setAdded(s.id)
            setAdding(false)
          }}
        />
      )}
      {reviewing && <Review server={reviewing} onClose={() => setReviewing(null)} onAccepted={(s) => (put(s), setReviewing(null))} />}
      {replacing && <ReplaceSecrets server={replacing} onClose={() => setReplacing(null)} onSaved={(s) => (put(s), setReplacing(null))} />}
      {deleting && (
        <Dialog open onClose={() => setDeleting(null)}>
          <DialogTitle>Delete {deleting.name}?</DialogTitle>
          <DialogContent>
            <Typography color="text.secondary">Workspaces that use it stop using it. Its stored sign-in and values are deleted.</Typography>
          </DialogContent>
          <DialogActions sx={{ px: 3, pb: 2 }}>
            <Button onClick={() => setDeleting(null)}>Cancel</Button>
            <Button variant="contained" color="error" onClick={() => remove(deleting)}>Delete</Button>
          </DialogActions>
        </Dialog>
      )}
    </Box>
  )
}
