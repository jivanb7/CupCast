/**
 * Tabs — horizontal pill-style tab navigation with gold underline on active.
 *
 * Controlled component. The parent owns the active tab state and update logic
 * (e.g. URL query string sync, localStorage). This component just renders the
 * trigger row and emits onChange.
 *
 * Props:
 *   tabs:    Array<{ id: string, label: string, count?: number }>
 *   active:  string  (id of the currently active tab)
 *   onChange:(id: string) => void
 *   ariaLabel: string  (e.g. "World Cup sections") — required for a11y
 *   className: string  (optional — appended to outer wrapper)
 *
 * Keyboard:
 *   ← / → arrow keys cycle through tabs (wraps at edges).
 *   Tab key moves focus past the whole tablist.
 */
export default function Tabs({ tabs, active, onChange, ariaLabel, className = '' }) {
  if (!tabs?.length) return null

  function handleKeyDown(e) {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    e.preventDefault()
    const idx = tabs.findIndex((t) => t.id === active)
    if (idx === -1) return
    const next =
      e.key === 'ArrowRight'
        ? (idx + 1) % tabs.length
        : (idx - 1 + tabs.length) % tabs.length
    onChange(tabs[next].id)
  }

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      onKeyDown={handleKeyDown}
      className={`flex gap-1 border-b border-white/[0.06] mb-4 ${className}`}
    >
      {tabs.map((tab) => {
        const isActive = tab.id === active
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={isActive}
            aria-controls={`tabpanel-${tab.id}`}
            tabIndex={isActive ? 0 : -1}
            onClick={() => onChange(tab.id)}
            className={`relative px-4 py-2.5 text-sm font-semibold transition-colors duration-200 cursor-pointer ${
              isActive
                ? 'text-foreground'
                : 'text-foreground-muted hover:text-foreground'
            }`}
          >
            {tab.label}
            {typeof tab.count === 'number' && (
              <span
                className={`ml-1.5 text-[11px] font-bold ${
                  isActive ? 'text-accent-gold' : 'text-foreground-muted'
                }`}
              >
                {tab.count}
              </span>
            )}
            {isActive && (
              <span className="absolute -bottom-px left-3 right-3 h-0.5 bg-accent-gold rounded-full" />
            )}
          </button>
        )
      })}
    </div>
  )
}

/**
 * TabPanel — accessible region wrapper. Use one per tab. Pass `active` to
 * decide whether to render its children. Hidden tabs unmount, which keeps the
 * page light when the user is on the other tab.
 */
export function TabPanel({ id, active, children }) {
  if (id !== active) return null
  return (
    <div
      role="tabpanel"
      id={`tabpanel-${id}`}
      aria-labelledby={`tab-${id}`}
      tabIndex={0}
      className="focus:outline-none"
    >
      {children}
    </div>
  )
}
