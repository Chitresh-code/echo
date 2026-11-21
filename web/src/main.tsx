import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import { AuthProvider, RequireAuth } from './auth'
import { Agents } from './pages/Agents'
import { Credentials } from './pages/Credentials'
import { SignIn } from './pages/SignIn'
import { EchoTheme } from './theme'

// The Agent page carries Monaco, by far the largest part of the app, so it loads only when opened.
const Agent = lazy(() => import('./pages/Agent'))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <EchoTheme>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/signin" element={<SignIn />} />
            <Route path="/" element={<RequireAuth><Agents /></RequireAuth>} />
            <Route path="/credentials" element={<RequireAuth><Credentials /></RequireAuth>} />
            <Route path="/agents/:agentId" element={<RequireAuth><Suspense><Agent /></Suspense></RequireAuth>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </EchoTheme>
  </StrictMode>,
)
