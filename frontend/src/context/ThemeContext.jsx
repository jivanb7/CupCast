import { createContext, useContext, useEffect, useState, useCallback } from 'react'

const ThemeContext = createContext({ theme: 'night', toggle: () => {} })

const STORAGE_KEY = 'cc.theme'

function readInitialTheme() {
  if (typeof window === 'undefined') return 'night'
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'day' || stored === 'night') return stored
  } catch {}
  return 'night'
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(readInitialTheme)

  useEffect(() => {
    const root = document.documentElement
    root.setAttribute('data-theme', theme)
    try { window.localStorage.setItem(STORAGE_KEY, theme) } catch {}
  }, [theme])

  const toggle = useCallback(
    () => setTheme((t) => (t === 'night' ? 'day' : 'night')),
    []
  )

  return (
    <ThemeContext.Provider value={{ theme, toggle }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  return useContext(ThemeContext)
}
