export default function LoadingSpinner({ size = 'md', label = 'Loading' }) {
  const dims = size === 'sm' ? 'w-5 h-5' : size === 'lg' ? 'w-10 h-10' : 'w-6 h-6'
  const border = size === 'lg' ? 'border-[3px]' : 'border-2'

  return (
    <div className="flex flex-col items-center gap-3" role="status" aria-label={label}>
      <div
        className={`${dims} ${border} border-elevated border-t-accent-gold rounded-full animate-spin`}
      />
      {size === 'lg' && (
        <span className="text-xs text-foreground-muted">{label}</span>
      )}
    </div>
  )
}
