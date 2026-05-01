/* AuthContext — façade auth for the demo
 *
 * Pure-frontend, localStorage-backed. No real auth, no backend, no Stripe.
 * The whole point is to give the demo the *feel* of a real product:
 *   - First visit lands on /login, the user clicks "Try the demo"
 *   - localStorage flag is set, the rest of the app behaves as if a Season
 *     Ticket subscriber is logged in (profile icon in nav, "Your plan" on
 *     the Pricing page, etc.)
 *   - Sign out clears the flag and bounces back to /login
 *
 * Demo user is hard-coded as a Season Ticket holder because that tier
 * matches what the app actually delivers today (Director's Box has features
 * like programmatic API + closing-line history that don't exist yet — would
 * be a broken promise to demo as that tier).
 */

import { createContext, useContext, useEffect, useMemo, useState } from 'react'

const STORAGE_KEY = 'cupcast_demo_active'

// Demo user profile that gets surfaced through useAuth() once signed in.
// Keep all the demo-mode pretend-data in one place so nothing else has to
// invent it inline.
const DEMO_USER = {
  email: 'demo@cupcast.example',
  displayName: 'Demo user',
  initial: 'D',
  tier: 'season',          // 'matchday' | 'season' | 'directors'
  tierLabel: 'Season Ticket',
}

// Synchronous initial read so the auto-redirect guard doesn't flash the
// dashboard before kicking the user to /login.
function readFlag() {
  if (typeof window === 'undefined') return false
  try {
    return window.localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [isSignedIn, setIsSignedIn] = useState(readFlag)

  // If the user opens the site in a second tab and signs in/out there,
  // mirror that here so both tabs stay consistent.
  useEffect(() => {
    function onStorage(e) {
      if (e.key !== STORAGE_KEY) return
      setIsSignedIn(e.newValue === '1')
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const value = useMemo(
    () => ({
      isSignedIn,
      user: isSignedIn ? DEMO_USER : null,
      signInAsDemo() {
        try {
          window.localStorage.setItem(STORAGE_KEY, '1')
        } catch {}
        setIsSignedIn(true)
      },
      signOut() {
        try {
          window.localStorage.removeItem(STORAGE_KEY)
        } catch {}
        setIsSignedIn(false)
      },
    }),
    [isSignedIn]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used inside <AuthProvider>')
  }
  return ctx
}
