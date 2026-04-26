import { Sun, Moon } from 'lucide-react'
import { useTheme } from '../../context/ThemeContext'

/**
 * ThemeToggle — icon-only button. Lives in the navbar slot after the
 * last nav link, separated by a thin vertical divider. Per UI placement
 * feedback: never absolute-positioned over existing chrome.
 */
export default function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const isNight = theme === 'night'

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Switch to ${isNight ? 'day' : 'night'} mode`}
      title={`Switch to ${isNight ? 'day' : 'night'} mode`}
      className="cc-theme-toggle ml-2 inline-flex h-8 w-8 items-center justify-center rounded-full border border-white/10 text-foreground-muted hover:text-foreground hover:border-accent-gold/40 transition-colors cursor-pointer"
    >
      {isNight ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
    </button>
  )
}
