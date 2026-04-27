// CupCast time helpers
// =====================
// Backend stores `match_date` (YYYY-MM-DD) and `kickoff_time` (HH:MM) in UTC.
// Frontend always renders in the viewer's local timezone, defaulting to
// Pacific because that's where the team works from. The Intl APIs handle
// DST transparently — no luxon, no moment, no manual DST math.

export const DEFAULT_TZ = 'America/Los_Angeles'

// Combine API match_date + kickoff_time into a JS Date interpreted as UTC.
// Returns null when either piece is missing or unparseable.
export function buildKickoffDate(matchDate, kickoffTime) {
  if (!matchDate) return null
  const t = (kickoffTime || '00:00').slice(0, 5)
  const iso = `${matchDate}T${t}:00Z`
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d
}

// Day-key in a target timezone — "2026-05-02"-style. Used so two timestamps
// that fall on the same local day produce the same key, even across DST.
export function dayKeyIn(date, tz = DEFAULT_TZ) {
  if (!date) return ''
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: tz,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
  return fmt.format(date) // en-CA gives YYYY-MM-DD by default
}

export function isLocalToday(date, tz = DEFAULT_TZ) {
  if (!date) return false
  return dayKeyIn(date, tz) === dayKeyIn(new Date(), tz)
}

export function isLocalTomorrow(date, tz = DEFAULT_TZ) {
  if (!date) return false
  // 36-hour offset crosses the next civil midnight even on DST-transition
  // nights (which are 23 or 25 hours long). dayKeyIn folds to the local
  // calendar date so the extra 12 h is harmless.
  const tomorrow = new Date(Date.now() + 36 * 3600 * 1000)
  return dayKeyIn(date, tz) === dayKeyIn(tomorrow, tz)
}

// Format the kick-off time. fmt='24h' → "13:30", fmt='12h' → "1:30 PM".
export function formatKickoffTime(date, { fmt = '24h', tz = DEFAULT_TZ } = {}) {
  if (!date) return ''
  const opts = fmt === '12h'
    ? { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: tz }
    : { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: tz }
  return new Intl.DateTimeFormat('en-US', opts).format(date)
}

// Format the date side. Returns "Today", "Tomorrow", or "Sat May 2" /
// "May 2" depending on `weekday` flag.
export function formatKickoffDate(date, { tz = DEFAULT_TZ, weekday = false, relative = true } = {}) {
  if (!date) return ''
  if (relative) {
    if (isLocalToday(date, tz)) return 'Today'
    if (isLocalTomorrow(date, tz)) return 'Tomorrow'
  }
  const opts = weekday
    ? { timeZone: tz, weekday: 'short', month: 'short', day: 'numeric' }
    : { timeZone: tz, month: 'short', day: 'numeric' }
  return new Intl.DateTimeFormat('en-US', opts).format(date)
}

// Concise display: "Today · 06:30" / "Sat May 2 · 06:30" — used on cards
// where space is tight but the date matters.
export function formatKickoffShort(date, opts = {}) {
  if (!date) return ''
  const datePart = formatKickoffDate(date, opts)
  const timePart = formatKickoffTime(date, opts)
  return `${datePart} · ${timePart}`
}

// Ago / countdown helpers for the LIVE badge + UpdatedBadge — keep here so
// every consumer rounds the same way.
export function secondsUntil(date) {
  if (!date) return null
  return Math.floor((date.getTime() - Date.now()) / 1000)
}

export function tzAbbreviation(tz = DEFAULT_TZ, date = new Date()) {
  // Intl returns the localized short name; falls back to the offset if the
  // browser doesn't recognise the zone (e.g. older Safari).
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: tz,
      timeZoneName: 'short',
    }).formatToParts(date)
    const tzName = parts.find((p) => p.type === 'timeZoneName')
    return tzName?.value || ''
  } catch {
    return ''
  }
}
