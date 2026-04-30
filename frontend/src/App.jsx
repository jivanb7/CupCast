import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import Dashboard from './pages/Dashboard'

const Matches = lazy(() => import('./pages/Matches'))
const MatchDetail = lazy(() => import('./pages/MatchDetail'))
const WorldCup = lazy(() => import('./pages/WorldCup'))
const Model = lazy(() => import('./pages/Model'))
const Value = lazy(() => import('./pages/Value'))
const About = lazy(() => import('./pages/About'))
const Pricing = lazy(() => import('./pages/Pricing'))

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
        <Route path="/" element={<Dashboard />} />
        <Route path="/matches" element={<Matches />} />
        <Route path="/match/:matchId" element={<MatchDetail />} />
        <Route path="/world-cup" element={<WorldCup />} />
        <Route path="/model" element={<Model />} />
        <Route path="/value" element={<Value />} />
        <Route path="/about" element={<About />} />
        <Route path="/pricing" element={<Pricing />} />
      </Routes>
    </Suspense>
  )
}
