import { Zap } from 'lucide-react'

export default function ValuePickBadge({ direction = null, edge = null }) {
  return (
    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold uppercase tracking-wider bg-accent-gold/15 text-accent-gold border border-accent-gold/25">
      <Zap className="w-3 h-3" />
      VALUE{direction ? ` ${direction}` : ''}
      {edge != null ? ` +${Math.round(edge * 100)}%` : ''}
    </span>
  )
}
