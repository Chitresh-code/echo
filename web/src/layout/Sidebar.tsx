import Add from '@mui/icons-material/Add'
import DarkModeOutlined from '@mui/icons-material/DarkModeOutlined'
import KeyOutlined from '@mui/icons-material/KeyOutlined'
import LightModeOutlined from '@mui/icons-material/LightModeOutlined'
import MoreHoriz from '@mui/icons-material/MoreHoriz'
import PersonOutlined from '@mui/icons-material/PersonOutlined'
import ViewSidebarOutlined from '@mui/icons-material/ViewSidebarOutlined'
import {
  Alert, Box, Button, Divider, IconButton, Link, ListItemIcon, Menu, MenuItem, Tooltip, Typography,
} from '@mui/material'
import { useState, type ReactNode } from 'react'
import { NavLink, useMatch, useNavigate } from 'react-router'
import type { Agent } from '../api/types'
import { useAuth } from '../auth'
import { useMode } from '../theme'
import { Logo } from './Logo'
import { DeleteDialog, NameInput } from './WorkspaceActions'
import { useWorkspaces } from './workspaces'

const rowSx = {
  display: 'flex', alignItems: 'center', gap: 1.25, minHeight: 36, px: 1.25, borderRadius: '8px', color: 'text.primary',
  textDecoration: 'none', fontSize: 14, minWidth: 0,
  '&:hover': { bgcolor: 'var(--raised)' },
  '&.active, &[aria-current="page"]': { bgcolor: 'var(--accentSoft)', fontWeight: 500 },
  '&:focus-visible': { outline: '2px solid var(--accent)', outlineOffset: -2 },
}

function NavItem({ to, icon, label, collapsed, end }: { to: string; icon: ReactNode; label: string; collapsed: boolean; end?: boolean }) {
  const link = (
    <Link component={NavLink} to={to} end={end} aria-label={collapsed ? label : undefined} sx={{ ...rowSx, justifyContent: collapsed ? 'center' : undefined }}>
      {icon}
      {!collapsed && label}
    </Link>
  )
  return collapsed ? <Tooltip title={label} placement="right">{link}</Tooltip> : link
}

type Props = {
  /** The thin rail on wide screens: links as icons, no recent list. */
  collapsed?: boolean
  /** Collapses or expands; left out in the phone drawer, which closes instead. */
  onToggle?: () => void
}

/** The left side of every signed-in page: new workspace, credentials, recent workspaces, account. */
export function Sidebar({ collapsed = false, onToggle }: Props) {
  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 1, p: 1, bgcolor: 'background.paper' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: collapsed ? 'center' : 'space-between', minHeight: 40, px: collapsed ? 0 : 1 }}>
        {!collapsed && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, fontWeight: 600, fontSize: 15 }}>
            <Logo />
            Echo
          </Box>
        )}
        {onToggle && (
          <Tooltip title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} placement="right">
            <IconButton size="small" onClick={onToggle} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} aria-expanded={!collapsed}>
              <ViewSidebarOutlined fontSize="small" />
            </IconButton>
          </Tooltip>
        )}
      </Box>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25 }}>
        <NavItem to="/" end icon={<Add fontSize="small" />} label="New workspace" collapsed={collapsed} />
        <NavItem to="/credentials" icon={<KeyOutlined fontSize="small" />} label="Credentials" collapsed={collapsed} />
      </Box>
      {collapsed ? <Box sx={{ flexGrow: 1 }} /> : <Recent />}
      <Account collapsed={collapsed} />
    </Box>
  )
}

function Recent() {
  const { workspaces, error, reload } = useWorkspaces()
  const openId = useMatch('/w/:agentId')?.params.agentId
  const navigate = useNavigate()
  const [menu, setMenu] = useState<{ anchor: HTMLElement; agent: Agent } | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const [deleting, setDeleting] = useState<Agent | null>(null)

  return (
    <Box component="section" aria-labelledby="recent-heading" sx={{ flexGrow: 1, minHeight: 0, display: 'flex', flexDirection: 'column', mt: 1 }}>
      <Typography id="recent-heading" component="h2" sx={{ px: 1.25, py: 0.5, fontSize: 12, fontWeight: 600, color: 'text.secondary' }}>
        Recent
      </Typography>
      {notice && <Alert severity="error" onClose={() => setNotice('')} sx={{ mx: 0.5, my: 0.5, fontSize: 13 }}>{notice}</Alert>}
      <Box sx={{ flexGrow: 1, minHeight: 0, overflowY: 'auto' }}>
        {error ? (
          <Box sx={{ px: 1.25, py: 1, display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 1 }}>
            <Typography color="text.secondary" sx={{ fontSize: 13 }}>Your workspaces did not load. {error}</Typography>
            <Button size="small" variant="outlined" onClick={reload} sx={{ minHeight: 32 }}>Retry</Button>
          </Box>
        ) : workspaces === null ? (
          <Typography color="text.secondary" sx={{ px: 1.25, py: 1, fontSize: 13 }} role="status">Loading…</Typography>
        ) : workspaces.length === 0 ? (
          <Typography color="text.secondary" sx={{ px: 1.25, py: 1, fontSize: 13 }}>Your workspaces show up here.</Typography>
        ) : (
          <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0, display: 'flex', flexDirection: 'column', gap: 0.25 }}>
            {workspaces.map((agent) => (
              <Box component="li" key={agent.id} sx={{ position: 'relative', '&:hover .more, &:focus-within .more': { opacity: 1 } }}>
                {editing === agent.id ? (
                  <NameInput
                    agent={agent}
                    onDone={(error) => {
                      setEditing(null)
                      setNotice(error ?? '')
                    }}
                    sx={{ width: '100%' }}
                  />
                ) : (
                  <>
                    <Link component={NavLink} to={`/w/${agent.id}`} title={agent.name} sx={{ ...rowSx, pr: 4.5 }}>
                      <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{agent.name}</Box>
                    </Link>
                    <IconButton
                      className="more"
                      size="small"
                      aria-label={`Options for ${agent.name}`}
                      aria-haspopup="menu"
                      onClick={(e) => setMenu({ anchor: e.currentTarget, agent })}
                      sx={{
                        position: 'absolute', right: 4, top: '50%', transform: 'translateY(-50%)', width: 28, height: 28,
                        opacity: agent.id === openId || menu?.agent.id === agent.id ? 1 : 0,
                        '@media (hover: none)': { opacity: 1 },
                      }}
                    >
                      <MoreHoriz fontSize="small" />
                    </IconButton>
                  </>
                )}
              </Box>
            ))}
          </Box>
        )}
      </Box>

      {/* Focus goes back to the options button by hand, except on Rename: there it belongs to the
          name field, and the menu's own restore (fixed when it opens) would end the rename at once. */}
      <Menu anchorEl={menu?.anchor} open={!!menu} onClose={() => { menu?.anchor.focus(); setMenu(null) }} disableRestoreFocus>
        <MenuItem onClick={() => { setEditing(menu!.agent.id); setMenu(null) }}>Rename</MenuItem>
        <MenuItem onClick={() => { menu!.anchor.focus(); setDeleting(menu!.agent); setMenu(null) }} sx={{ color: 'error.main' }}>Delete</MenuItem>
      </Menu>

      {deleting && (
        <DeleteDialog
          agent={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            setDeleting(null)
            if (deleting.id === openId) navigate('/')
          }}
        />
      )}
    </Box>
  )
}

function Account({ collapsed }: { collapsed: boolean }) {
  const { user, signOut } = useAuth()
  const { mode, toggle } = useMode()
  const navigate = useNavigate()
  const [menu, setMenu] = useState<HTMLElement | null>(null)
  const name = user?.name ?? 'Account'

  return (
    <>
      <Divider />
      <Box
        component="button"
        type="button"
        aria-label={collapsed ? 'Account' : undefined}
        aria-haspopup="menu"
        onClick={(e: React.MouseEvent<HTMLElement>) => setMenu(e.currentTarget)}
        sx={{ ...rowSx, border: 0, bgcolor: 'transparent', font: 'inherit', cursor: 'pointer', justifyContent: collapsed ? 'center' : undefined, minHeight: 44 }}
      >
        <Box component="span" sx={{ display: 'grid', placeItems: 'center', width: 28, height: 28, flexShrink: 0, borderRadius: 999, border: 1, borderColor: 'divider', bgcolor: 'var(--raised)' }}>
          <PersonOutlined fontSize="small" />
        </Box>
        {!collapsed && <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</Box>}
      </Box>
      <Menu
        anchorEl={menu}
        open={!!menu}
        onClose={() => setMenu(null)}
        anchorOrigin={{ vertical: 'top', horizontal: 'left' }}
        transformOrigin={{ vertical: 'bottom', horizontal: 'left' }}
      >
        <Box sx={{ px: 2, py: 1 }}>
          <Typography sx={{ fontWeight: 600 }}>{user?.name ?? 'Signed in'}</Typography>
          {user?.email && <Typography variant="body2" color="text.secondary">{user.email}</Typography>}
        </Box>
        <Divider />
        <MenuItem onClick={toggle}>
          <ListItemIcon>{mode === 'dark' ? <LightModeOutlined fontSize="small" /> : <DarkModeOutlined fontSize="small" />}</ListItemIcon>
          {mode === 'dark' ? 'Light theme' : 'Dark theme'}
        </MenuItem>
        <MenuItem
          onClick={async () => {
            setMenu(null)
            await signOut()
            navigate('/signin')
          }}
        >
          Sign out
        </MenuItem>
      </Menu>
    </>
  )
}
