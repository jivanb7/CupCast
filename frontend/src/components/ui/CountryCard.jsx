import { Link } from 'react-router-dom'
import CountryFlagSvg from './CountryFlagSvg'

/**
 * CountryCard — clickable country tile from the dashboard hub.
 *
 * Props:
 *   country: { slug, name, subLabel, todayCount, upcomingCount, flagSlug? }
 *
 * Click navigates to /matches?country={slug}.
 */
export default function CountryCard({ country }) {
  if (!country) return null
  const { slug, name, subLabel, todayCount = 0, upcomingCount = 0, flagSlug } = country
  const flag = flagSlug || slug

  return (
    <Link
      to={`/matches?country=${slug}`}
      className="group relative block overflow-hidden rounded-[14px] border border-white/8 bg-card p-[18px] transition-all duration-200 hover:-translate-y-0.5 hover:border-accent-gold/40"
      aria-label={`Explore ${name} matches`}
    >
      {/* gold glow on hover, subtle */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 transition-opacity duration-200"
        style={{ background: 'linear-gradient(180deg, transparent 60%, rgba(245,158,11,0.04) 100%)' }}
      />

      <div className="flex items-center gap-3 mb-3.5">
        <CountryFlagSvg
          slug={flag}
          className="w-10 h-7 rounded-[4px] border border-white/8 shadow-sm flex-shrink-0"
        />
        <div className="min-w-0">
          <div className="text-[17px] font-extrabold tracking-[-0.01em] truncate">{name}</div>
          {subLabel && (
            <div className="text-[11px] text-foreground-muted mt-0.5 truncate">{subLabel}</div>
          )}
        </div>
      </div>

      <div className="relative z-10 flex justify-between items-center pt-2.5 border-t border-white/5 text-xs">
        <span>
          <span className="text-accent-gold font-bold">{todayCount} today</span>
          <span className="text-foreground-muted"> · {upcomingCount} upcoming</span>
        </span>
        <span className="text-accent-gold font-semibold transition-transform duration-200 group-hover:translate-x-1">→</span>
      </div>
    </Link>
  )
}
