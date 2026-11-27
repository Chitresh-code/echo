import MenuIcon from '@mui/icons-material/Menu'
import { Box, Drawer, IconButton, useMediaQuery } from '@mui/material'
import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router'
import { Logo } from './Logo'
import { Sidebar } from './Sidebar'
import { WorkspacesProvider } from './workspaces'

const STORED = 'echo.sidebar'

function readCollapsed() {
  try {
    return localStorage.getItem(STORED) === 'collapsed'
  } catch {
    return false
  }
}

/** Every signed-in page: the sidebar on the left (a drawer on narrow screens) and the page. */
export function Shell() {
  const wide = useMediaQuery('(min-width:900px)', { noSsr: true })
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [drawer, setDrawer] = useState(false)
  const { pathname } = useLocation()
  useEffect(() => setDrawer(false), [pathname])

  function toggle() {
    const next = !collapsed
    setCollapsed(next)
    try {
      localStorage.setItem(STORED, next ? 'collapsed' : 'open')
    } catch {
      // Private windows can refuse storage; the choice then lasts until reload.
    }
  }

  return (
    <WorkspacesProvider>
      <Box sx={{ height: '100%', display: 'flex' }}>
        {wide ? (
          <Box component="nav" aria-label="Workspaces" sx={{ width: collapsed ? 60 : 264, flexShrink: 0, borderRight: 1, borderColor: 'divider' }}>
            <Sidebar collapsed={collapsed} onToggle={toggle} />
          </Box>
        ) : (
          <Drawer open={drawer} onClose={() => setDrawer(false)}>
            <Box component="nav" aria-label="Workspaces" sx={{ width: 280, height: '100%' }}>
              <Sidebar />
            </Box>
          </Drawer>
        )}
        <Box sx={{ flexGrow: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
          {!wide && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1, minHeight: 48, borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper' }}>
              <IconButton aria-label="Open sidebar" onClick={() => setDrawer(true)}>
                <MenuIcon />
              </IconButton>
              <Logo />
              <Box component="span" sx={{ fontWeight: 600 }}>Echo</Box>
            </Box>
          )}
          <Box sx={{ flexGrow: 1, minHeight: 0, overflow: 'auto' }}>
            <Outlet />
          </Box>
        </Box>
      </Box>
    </WorkspacesProvider>
  )
}
