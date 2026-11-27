import { useEffect } from 'react'
import { useBlocker } from 'react-router'

/** While a turn runs, leaving the workspace would stop it, so leaving asks first: a navigation in
 *  the app is held until Stay or Leave, and closing or reloading the tab gets the browser's warning.
 *  Sign out is never held, since the session is already gone. */
// shortcut: the turn lives in this page's stream, so leaving stops it; drop the guard once turns run on the server and any tab can reattach.
export function useLeaveGuard(stop: (() => void) | null) {
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) => !!stop && currentLocation.pathname !== nextLocation.pathname && nextLocation.pathname !== '/signin',
  )

  useEffect(() => {
    if (!stop) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [stop])

  // The turn ended while the question was open: nothing to stop any more.
  useEffect(() => {
    if (!stop && blocker.state === 'blocked') blocker.proceed()
  }, [stop, blocker])

  return {
    asking: blocker.state === 'blocked',
    stay: () => blocker.reset?.(),
    leave: () => {
      stop?.()
      blocker.proceed?.()
    },
  }
}
