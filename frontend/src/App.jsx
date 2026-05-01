import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import RequireAuth from './components/RequireAuth'

// Login + Pricing are NOT wrapped in RequireAuth — Login obviously can't
// be (would loop), and Pricing stays public so it can act as the marketing
// surface even when the visitor hasn't clicked through the demo gate.
const Login = lazy(() => import('./pages/Login'))
const Pricing = lazy(() => import('./pages/Pricing'))

const Matches = lazy(() => import('./pages/Matches'))
const MatchDetail = lazy(() => import('./pages/MatchDetail'))
const WorldCup = lazy(() => import('./pages/WorldCup'))
const Model = lazy(() => import('./pages/Model'))
const Value = lazy(() => import('./pages/Value'))
const About = lazy(() => import('./pages/About'))
const Billing = lazy(() => import('./pages/Billing'))

function PageFallback() {
  return (
    <div
      className="cc-root cc-night"
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div className="cc-eyebrow">Loading…</div>
    </div>
  )
}

export default function App() {
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        {/* Public routes */}
        <Route path="/login" element={<Login />} />
        <Route path="/pricing" element={<Pricing />} />

        {/* Gated routes — redirect to /login if the demo flag is missing. */}
        <Route path="/" element={<RequireAuth><Dashboard /></RequireAuth>} />
        <Route path="/matches" element={<RequireAuth><Matches /></RequireAuth>} />
        <Route path="/match/:matchId" element={<RequireAuth><MatchDetail /></RequireAuth>} />
        <Route path="/world-cup" element={<RequireAuth><WorldCup /></RequireAuth>} />
        <Route path="/model" element={<RequireAuth><Model /></RequireAuth>} />
        <Route path="/value" element={<RequireAuth><Value /></RequireAuth>} />
        <Route path="/about" element={<RequireAuth><About /></RequireAuth>} />
        <Route path="/billing" element={<RequireAuth><Billing /></RequireAuth>} />
      </Routes>
    </Suspense>
  )
}
