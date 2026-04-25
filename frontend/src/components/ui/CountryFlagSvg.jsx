/**
 * CountryFlagSvg — small inline flag SVGs used by CountryCard and
 * LeagueFilterBar. Verbatim copies of the SVGs from dashboard-v2 /
 * matches-v5 mockups (locked design assets, intentionally not refactored).
 *
 * Usage:
 *   <CountryFlagSvg slug="england" className="w-10 h-7" />
 */

const SVGS = {
  england: (
    <svg viewBox="0 0 60 42" preserveAspectRatio="none">
      <rect width="60" height="42" fill="#fff" />
      <rect x="26" width="8" height="42" fill="#ce1124" />
      <rect y="17" width="60" height="8" fill="#ce1124" />
    </svg>
  ),
  spain: (
    <svg viewBox="0 0 60 42" preserveAspectRatio="none">
      <rect width="60" height="42" fill="#aa151b" />
      <rect y="10.5" width="60" height="21" fill="#f1bf00" />
    </svg>
  ),
  italy: (
    <svg viewBox="0 0 60 42" preserveAspectRatio="none">
      <rect width="20" height="42" fill="#008c45" />
      <rect x="20" width="20" height="42" fill="#f4f5f0" />
      <rect x="40" width="20" height="42" fill="#cd212a" />
    </svg>
  ),
  germany: (
    <svg viewBox="0 0 60 42" preserveAspectRatio="none">
      <rect width="60" height="14" fill="#000" />
      <rect y="14" width="60" height="14" fill="#dd0000" />
      <rect y="28" width="60" height="14" fill="#ffce00" />
    </svg>
  ),
  france: (
    <svg viewBox="0 0 60 42" preserveAspectRatio="none">
      <rect width="20" height="42" fill="#0055a4" />
      <rect x="20" width="20" height="42" fill="#fff" />
      <rect x="40" width="20" height="42" fill="#ef4135" />
    </svg>
  ),
  usa: (
    <svg viewBox="0 0 60 42" preserveAspectRatio="none">
      <rect width="60" height="42" fill="#b22234" />
      <rect y="3" width="60" height="3" fill="#fff" />
      <rect y="9" width="60" height="3" fill="#fff" />
      <rect y="15" width="60" height="3" fill="#fff" />
      <rect y="21" width="60" height="3" fill="#fff" />
      <rect y="27" width="60" height="3" fill="#fff" />
      <rect y="33" width="60" height="3" fill="#fff" />
      <rect y="39" width="60" height="3" fill="#fff" />
      <rect width="24" height="22" fill="#3c3b6e" />
    </svg>
  ),
  rest: (
    <svg viewBox="0 0 60 42" preserveAspectRatio="none">
      <rect width="60" height="42" fill="#1e3a8a" />
      <circle cx="30" cy="21" r="13" fill="none" stroke="#d4a84c" strokeWidth="1.5" />
      <ellipse cx="30" cy="21" rx="13" ry="5" fill="none" stroke="#d4a84c" strokeWidth="1" />
      <line x1="17" y1="21" x2="43" y2="21" stroke="#d4a84c" strokeWidth="1" />
      <line x1="30" y1="8" x2="30" y2="34" stroke="#d4a84c" strokeWidth="1" />
    </svg>
  ),
}

export default function CountryFlagSvg({ slug, className = '' }) {
  const svg = SVGS[slug]
  if (!svg) return null
  return <span className={`inline-block overflow-hidden ${className}`}>{svg}</span>
}

export const COUNTRY_SLUGS = Object.keys(SVGS)
