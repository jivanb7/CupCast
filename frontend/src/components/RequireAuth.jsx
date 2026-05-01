/* RequireAuth — route-level guard for the demo façade auth.
 *
 * Wraps any page that should be hidden behind the login screen. Reads the
 * AuthContext flag synchronously on the first render so unauthenticated
 * visitors are bounced to /login without ever seeing the protected page
 * flash on screen. After the demo button is clicked the flag flips, the
 * <Navigate> stops firing, and the protected page renders normally.
 *
 * /login itself is not wrapped (would loop). /pricing is not wrapped
 * either — the Pricing page stays publicly visible so it can serve as the
 * marketing surface, and its CTAs route logged-out clicks to /login.
 */

import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function RequireAuth({ children }) {
  const { isSignedIn } = useAuth()
  const location = useLocation()

  if (!isSignedIn) {
    // Pass `from` so /login could one day route them back to where they
    // tried to go. Demo button currently always returns to /, but the
    // hook is in place if we want it later.
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return children
}
