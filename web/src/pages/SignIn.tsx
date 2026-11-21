import Login from '@mui/icons-material/Login'
import { Box, Button, Typography } from '@mui/material'
import { Navigate } from 'react-router'
import { useAuth } from '../auth'
import { Logo } from '../layout/Logo'

export function SignIn() {
  const { user } = useAuth()
  if (user) return <Navigate to="/" replace />
  return (
    <Box sx={{ minHeight: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', px: 2, py: 3 }}>
      <Box component="main" sx={{ width: '100%', maxWidth: 400, display: 'flex', flexDirection: 'column', gap: 3.5 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25 }}>
          <Logo size={32} />
          <Typography sx={{ fontSize: 22, fontWeight: 600 }}>Echo</Typography>
        </Box>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          <Typography component="h1" sx={{ fontSize: 28, lineHeight: 1.2, fontWeight: 600, letterSpacing: '-0.01em' }}>
            An agent that learns your job
          </Typography>
          <Typography color="text.secondary" sx={{ fontSize: 15, lineHeight: 1.55 }}>
            Teach Echo one task by doing it together. It remembers your corrections, writes its own skills and gets better each time you come back.
          </Typography>
        </Box>
        {/* A full page load, not a client route: sign-in leaves for Microsoft and comes back. */}
        <Button variant="contained" href="/api/auth/login" startIcon={<Login />} sx={{ minHeight: 44, fontSize: 15 }}>
          Sign in with Microsoft
        </Button>
        <Typography color="text.secondary" sx={{ pt: 2.5, borderTop: 1, borderColor: 'divider', fontSize: 13, lineHeight: 1.55 }}>
          Use your work account. Who can sign in is managed by your admin in Microsoft Entra.
        </Typography>
      </Box>
    </Box>
  )
}
