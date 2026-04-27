import { useEffect, useState } from 'react'

export default function useCCTheme(defaultTheme = 'night') {
  const [theme, setTheme] = useState(() => {
    if (typeof window === 'undefined') return defaultTheme
    try { return localStorage.getItem('cc-theme') || defaultTheme } catch { return defaultTheme }
  })
  useEffect(() => {
    try { localStorage.setItem('cc-theme', theme) } catch { /* ignore */ }
  }, [theme])
  return [theme, setTheme]
}
