import { createTheme, CssBaseline, GlobalStyles, ThemeProvider, useMediaQuery } from '@mui/material'
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'

export type Mode = 'dark' | 'light'

// The design's tokens. Components use them through the MUI palette, or as CSS variables (set on
// :root below) where the palette has no matching slot, such as the diff colors.
export const TOKENS = {
  dark: {
    bg: '#0E1012', panel: '#15181B', raised: '#1F2328', border: '#2A2F35', text: '#E6E8EA', muted: '#9AA1A9',
    accent: '#2DD4BF', onAccent: '#062925', accentSoft: 'rgba(45,212,191,0.12)', add: 'rgba(74,222,128,0.12)',
    addText: '#86EFAC', del: 'rgba(248,113,113,0.13)', delText: '#FCA5A5', warn: '#FBBF24',
  },
  light: {
    bg: '#F6F7F8', panel: '#FFFFFF', raised: '#EEF0F2', border: '#D9DDE1', text: '#14171A', muted: '#555D66',
    accent: '#0F766E', onAccent: '#FFFFFF', accentSoft: 'rgba(15,118,110,0.10)', add: 'rgba(22,163,74,0.10)',
    addText: '#166534', del: 'rgba(220,38,38,0.09)', delText: '#991B1B', warn: '#A16207',
  },
} as const

export const MONO = "'JetBrains Mono', ui-monospace, monospace"
const STORED = 'echo.theme'

function build(mode: Mode) {
  const t = TOKENS[mode]
  return createTheme({
    palette: {
      mode,
      primary: { main: t.accent, contrastText: t.onAccent },
      error: { main: t.delText },
      warning: { main: t.warn },
      success: { main: t.addText },
      background: { default: t.bg, paper: t.panel },
      text: { primary: t.text, secondary: t.muted },
      divider: t.border,
    },
    typography: { fontFamily: 'Inter, system-ui, sans-serif', fontSize: 14, button: { textTransform: 'none', fontWeight: 600 } },
    shape: { borderRadius: 8 },
    components: {
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: { root: { borderRadius: 10, minHeight: 40 }, outlined: { borderColor: t.border, color: t.text } },
      },
      MuiPaper: { styleOverrides: { root: { backgroundImage: 'none' } } },
      MuiOutlinedInput: {
        styleOverrides: {
          root: { backgroundColor: t.bg, '& .MuiOutlinedInput-notchedOutline': { borderColor: t.border } },
        },
      },
      MuiDialog: { styleOverrides: { paper: { border: `1px solid ${t.border}`, borderRadius: 12 } } },
      MuiMenu: { styleOverrides: { paper: { border: `1px solid ${t.border}` } } },
      MuiTooltip: { defaultProps: { enterDelay: 400 } },
    },
  })
}

const ModeContext = createContext<{ mode: Mode; toggle: () => void }>({ mode: 'dark', toggle: () => {} })

export const useMode = () => useContext(ModeContext)

function readStored(): Mode | null {
  try {
    const value = localStorage.getItem(STORED)
    return value === 'dark' || value === 'light' ? value : null
  } catch {
    return null
  }
}

/** Follows the system's light or dark setting until the user picks one with the toggle. */
export function EchoTheme({ children }: { children: ReactNode }) {
  const prefersDark = useMediaQuery('(prefers-color-scheme: dark)')
  const [chosen, setChosen] = useState<Mode | null>(readStored)
  const mode: Mode = chosen ?? (prefersDark ? 'dark' : 'light')
  const theme = useMemo(() => build(mode), [mode])
  const value = useMemo(
    () => ({
      mode,
      toggle: () => {
        const next: Mode = mode === 'dark' ? 'light' : 'dark'
        setChosen(next)
        try {
          localStorage.setItem(STORED, next)
        } catch {
          // Private windows can refuse storage; the choice then lasts until reload.
        }
      },
    }),
    [mode],
  )
  const vars = Object.fromEntries(Object.entries(TOKENS[mode]).map(([k, v]) => [`--${k}`, v]))
  return (
    <ModeContext.Provider value={value}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <GlobalStyles styles={{ ':root': vars, 'html, body, #root': { height: '100%' }, code: { fontFamily: MONO } }} />
        {children}
      </ThemeProvider>
    </ModeContext.Provider>
  )
}
