import { Clock } from 'lucide-react'

export default function BracketView({ bracket = null }) {
  if (!bracket) {
    return (
      <div className="cc-card p-8 text-center">
        <Clock className="w-8 h-8 text-foreground-muted mx-auto mb-3" />
        <p className="text-foreground-muted font-medium">
          Knockout bracket will be available once the group stage completes.
        </p>
        <p className="text-sm text-foreground-muted/60 mt-2">
          Group stage ends June 27, 2026.
        </p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <div className="min-w-max p-4">
        <p className="text-foreground-muted text-sm">Bracket visualization coming soon.</p>
      </div>
    </div>
  )
}
