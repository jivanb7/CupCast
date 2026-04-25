import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import Navbar from './components/layout/Navbar'
import Footer from './components/layout/Footer'
import LoadingSpinner from './components/ui/LoadingSpinner'
import Dashboard from './pages/Dashboard'

const MatchDetail = lazy(() => import('./pages/MatchDetail'))
const Matches = lazy(() => import('./pages/Matches'))
const WorldCup = lazy(() => import('./pages/WorldCup'))
const ModelPerformance = lazy(() => import('./pages/ModelPerformance'))
const About = lazy(() => import('./pages/About'))
const ValuePicks = lazy(() => import('./pages/ValuePicks'))

function PageFallback() {
  return (
    <div className="flex justify-center pt-32">
      <LoadingSpinner size="lg" label="Loading page" />
    </div>
  )
}

export default function App() {
  return (
    <div className="min-h-screen bg-deep text-foreground flex flex-col">
      <Navbar />
      <main className="flex-1">
        <Suspense fallback={<PageFallback />}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/matches" element={<Matches />} />
            <Route path="/match/:matchId" element={<MatchDetail />} />
            <Route path="/world-cup" element={<WorldCup />} />
            <Route path="/model-performance" element={<ModelPerformance />} />
            <Route path="/value-picks" element={<ValuePicks />} />
            <Route path="/about" element={<About />} />
          </Routes>
        </Suspense>
      </main>
      <Footer />
    </div>
  )
}
