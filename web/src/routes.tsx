import { lazy, Suspense } from 'react'
import { Navigate, Outlet, useParams, type RouteObject } from 'react-router'
import { AuthProvider, RequireAuth } from './auth'
import { Shell } from './layout/Shell'
import { Credentials } from './pages/Credentials'
import { Home } from './pages/Home'
import { McpServers } from './pages/McpServers'
import { SignIn } from './pages/SignIn'

// The workspace page carries Monaco, by far the largest part of the app, so it loads only when opened.
const Workspace = lazy(() => import('./pages/Workspace'))
// The usage chart's library is large and only this page uses it.
const Usage = lazy(() => import('./pages/Usage').then((m) => ({ default: m.Usage })))

// Links and bookmarks from before workspaces had their own address.
function OldAgentLink() {
  const { agentId = '' } = useParams()
  return <Navigate to={`/w/${agentId}`} replace />
}

export const routes: RouteObject[] = [
  {
    element: <AuthProvider><Outlet /></AuthProvider>,
    children: [
      { path: '/signin', element: <SignIn /> },
      {
        element: <RequireAuth><Shell /></RequireAuth>,
        children: [
          { index: true, element: <Home /> },
          { path: '/w/:agentId', element: <Suspense><Workspace /></Suspense> },
          { path: '/w/:agentId/c/:chatId', element: <Suspense><Workspace /></Suspense> },
          { path: '/credentials', element: <Credentials /> },
          { path: '/mcp', element: <McpServers /> },
          { path: '/usage', element: <Suspense><Usage /></Suspense> },
          { path: '/agents/:agentId', element: <OldAgentLink /> },
        ],
      },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
]
