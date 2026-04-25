import CountryFlagSvg from './CountryFlagSvg'

/**
 * LeagueFilterBar — pill bar of country/competition filters.
 * Reused on all three Matches views (Today, Upcoming, Recent).
 *
 * Props:
 *   value:    active filter slug (string | null) — null/'all' = All
 *   onChange: (slug | null) => void
 *
 * The pipe (|) before "Rest of World" is a visual separator (it's a
 * meta-bucket of leagues that didn't get their own pill).
 */

const FILTERS = [
  { slug: null, label: 'All' },
  { slug: 'england', label: 'England', flag: 'england' },
  { slug: 'spain', label: 'Spain', flag: 'spain' },
  { slug: 'italy', label: 'Italy', flag: 'italy' },
  { slug: 'germany', label: 'Germany', flag: 'germany' },
  { slug: 'france', label: 'France', flag: 'france' },
  { slug: 'usa', label: 'USA', flag: 'usa' },
  { slug: 'ucl', label: 'UCL', badge: { bg: '#003c96', fg: '#d4a84c', icon: '★' } },
  { slug: 'world-cup', label: 'World Cup', badge: { bg: '#722f37', fg: '#d4a84c', icon: '♚' } },
  { slug: '__divider__', divider: true },
  { slug: 'rest', label: 'Rest of World', flag: 'rest' },
]

function Pill({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`inline-flex items-center gap-1.5 px-3 py-[5px] rounded-full text-xs border transition-colors cursor-pointer ${
        active
          ? 'bg-accent-gold text-deep border-accent-gold font-semibold'
          : 'bg-card text-foreground-muted border-white/8 hover:text-foreground hover:border-white/15'
      }`}
    >
      {children}
    </button>
  )
}

export default function LeagueFilterBar({ value, onChange }) {
  const current = value || null
  return (
    <div role="tablist" aria-label="League filter" className="flex flex-wrap items-center gap-1.5 mb-4">
      {FILTERS.map((f) => {
        if (f.divider) {
          return (
            <span
              key="divider"
              aria-hidden
              className="inline-block w-px h-5 bg-white/10 mx-1"
            />
          )
        }
        const active = current === f.slug
        return (
          <Pill key={f.slug ?? 'all'} active={active} onClick={() => onChange(f.slug)}>
            {f.flag && (
              <CountryFlagSvg
                slug={f.flag}
                className="w-4 h-3 rounded-[2px]"
              />
            )}
            {f.badge && (
              <span
                aria-hidden
                className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-[3px] text-[8px] font-extrabold"
                style={{ background: f.badge.bg, color: f.badge.fg }}
              >
                {f.badge.icon}
              </span>
            )}
            {f.label}
          </Pill>
        )
      })}
    </div>
  )
}

export { FILTERS as LEAGUE_FILTERS }
