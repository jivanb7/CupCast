const STYLES = {
  W: 'bg-accent-green',
  D: 'bg-accent-amber',
  L: 'bg-accent-red',
}

export default function FormBadge({ results = [] }) {
  return (
    <div className="flex gap-1" role="list" aria-label="Recent form results">
      {results.slice(-5).map((result, i) => (
        <span
          key={i}
          role="listitem"
          className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold text-deep ${STYLES[result] || 'bg-elevated'}`}
          aria-label={result === 'W' ? 'Win' : result === 'D' ? 'Draw' : 'Loss'}
        >
          {result}
        </span>
      ))}
    </div>
  )
}
