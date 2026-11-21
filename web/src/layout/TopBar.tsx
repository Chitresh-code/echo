import DarkModeOutlined from '@mui/icons-material/DarkModeOutlined'
import LightModeOutlined from '@mui/icons-material/LightModeOutlined'
import PersonOutlined from '@mui/icons-material/PersonOutlined'
import { Box, Divider, IconButton, Link, Menu, MenuItem, Tooltip, Typography } from '@mui/material'
import { useState, type ReactNode } from 'react'
import { NavLink, Link as RouterLink, useNavigate } from 'react-router'
import { useAuth } from '../auth'
import { useMode } from '../theme'
import { Logo } from './Logo'

const navSx = {
  color: 'text.secondary',
  textDecoration: 'none',
  '&.active': { color: 'text.primary', fontWeight: 500 },
  '&:hover': { color: 'text.primary' },
}

/** The bar at the top of every signed-in page. `children` sits after the logo (the Agent page's
 *  breadcrumb). */
export function TopBar({ children }: { children?: ReactNode }) {
  const { user, signOut } = useAuth()
  const { mode, toggle } = useMode()
  const navigate = useNavigate()
  const [menu, setMenu] = useState<HTMLElement | null>(null)

  return (
    <Box
      component="header"
      sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 2, px: 2, minHeight: 48, borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper' }}
    >
      <Link component={RouterLink} to="/" underline="none" sx={{ display: 'flex', alignItems: 'center', gap: 1, color: 'text.primary', fontWeight: 600, fontSize: 15 }}>
        <Logo />
        Echo
      </Link>
      {children}
      <Box sx={{ flexGrow: 1 }} />
      <Box component="nav" aria-label="Main" sx={{ display: 'flex', gap: 2 }}>
        <Link component={NavLink} to="/" end sx={navSx}>Agents</Link>
        <Link component={NavLink} to="/credentials" sx={navSx}>Credentials</Link>
      </Box>
      <Tooltip title={mode === 'dark' ? 'Light theme' : 'Dark theme'}>
        <IconButton size="small" onClick={toggle} aria-label={mode === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}>
          {mode === 'dark' ? <LightModeOutlined fontSize="small" /> : <DarkModeOutlined fontSize="small" />}
        </IconButton>
      </Tooltip>
      <IconButton
        aria-label="Account"
        onClick={(e) => setMenu(e.currentTarget)}
        sx={{ width: 32, height: 32, border: 1, borderColor: 'divider', bgcolor: 'var(--raised)' }}
      >
        <PersonOutlined fontSize="small" />
      </IconButton>
      <Menu anchorEl={menu} open={!!menu} onClose={() => setMenu(null)} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }} transformOrigin={{ vertical: 'top', horizontal: 'right' }}>
        <Box sx={{ px: 2, py: 1 }}>
          <Typography sx={{ fontWeight: 600 }}>{user?.name ?? 'Signed in'}</Typography>
          {user?.email && <Typography variant="body2" color="text.secondary">{user.email}</Typography>}
        </Box>
        <Divider />
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
    </Box>
  )
}
