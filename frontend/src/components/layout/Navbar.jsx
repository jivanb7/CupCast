import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Menu, X, Trophy, TrendingUp, BarChart3, Globe, Info } from 'lucide-react'
import ThemeToggle from './ThemeToggle'

const NAV_LINKS = [
  { to: '/matches', label: 'Matches', icon: Trophy },
  { to: '/world-cup', label: 'World Cup 2026', gold: true, icon: Globe },
  { to: '/model-performance', label: 'Model', icon: BarChart3 },
  { to: '/about', label: 'About', icon: Info },
]

export default function Navbar() {
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <nav className="cc-nav fixed top-0 left-0 right-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <NavLink to="/" className="flex items-center gap-1.5 group">
            <span className="text-xl font-bold tracking-tight">
              <span className="text-accent-gold">Cup</span>
              <span className="text-foreground">Cast</span>
            </span>
          </NavLink>

          {/* Desktop Nav Links */}
          <div className="hidden md:flex items-center gap-1">
            {NAV_LINKS.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.end}
                className={({ isActive }) => {
                  const base = 'relative px-3 py-2 text-sm font-medium transition-colors duration-200 rounded-btn'
                  if (isActive) {
                    return `${base} ${link.gold ? 'text-accent-gold' : 'text-foreground'}`
                  }
                  return `${base} ${link.gold ? 'text-accent-gold/70 hover:text-accent-gold' : 'text-foreground-muted hover:text-foreground'}`
                }}
              >
                {({ isActive }) => (
                  <>
                    {link.label}
                    {isActive && (
                      <span className="absolute bottom-0 left-3 right-3 h-0.5 bg-accent-gold rounded-full" />
                    )}
                  </>
                )}
              </NavLink>
            ))}
            <span
              className="mx-1 h-5 w-px"
              style={{ background: 'var(--nav-divider)' }}
              aria-hidden="true"
            />
            <ThemeToggle />
          </div>

          {/* Mobile hamburger */}
          <button
            type="button"
            className="md:hidden p-2 text-foreground-muted hover:text-foreground transition-colors duration-200 cursor-pointer"
            onClick={() => setMenuOpen(!menuOpen)}
            aria-expanded={menuOpen}
            aria-label="Toggle navigation menu"
          >
            {menuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>

        {/* Mobile menu */}
        {menuOpen && (
          <div
            className="md:hidden py-2 pb-4 border-t"
            style={{ borderColor: 'var(--nav-border)' }}
          >
            {NAV_LINKS.map((link) => {
              const Icon = link.icon
              return (
                <NavLink
                  key={link.to}
                  to={link.to}
                  end={link.end}
                  onClick={() => setMenuOpen(false)}
                  className={({ isActive }) => {
                    const base = 'flex items-center gap-3 px-3 py-2.5 text-sm font-medium rounded-btn transition-colors duration-200'
                    if (isActive) {
                      return `${base} ${link.gold ? 'text-accent-gold bg-accent-gold/10' : 'text-foreground bg-white/5'}`
                    }
                    return `${base} text-foreground-muted hover:text-foreground hover:bg-white/5`
                  }}
                >
                  <Icon className="w-4 h-4" />
                  {link.label}
                </NavLink>
              )
            })}
            <div className="mt-2 pt-2 border-t border-white/5 px-3 flex items-center justify-between">
              <span className="text-xs text-foreground-muted uppercase tracking-widest">Theme</span>
              <ThemeToggle />
            </div>
          </div>
        )}
      </div>
    </nav>
  )
}
