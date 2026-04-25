/**
 * Pagination — `‹ Prev  1  2 … 18  Next ›` numeric pagination.
 *
 * Smart ellipsis: always shows first, last, current ±1.
 * Props:
 *   page:        1-indexed current page
 *   pageCount:   total pages
 *   onPageChange: (page: number) => void
 */

function buildPages(page, pageCount) {
  if (pageCount <= 7) {
    return Array.from({ length: pageCount }, (_, i) => i + 1)
  }
  const pages = new Set([1, pageCount, page, page - 1, page + 1])
  const sorted = [...pages].filter((p) => p >= 1 && p <= pageCount).sort((a, b) => a - b)
  const out = []
  for (let i = 0; i < sorted.length; i += 1) {
    out.push(sorted[i])
    if (i < sorted.length - 1 && sorted[i + 1] - sorted[i] > 1) out.push('…')
  }
  return out
}

function Btn({ children, active, disabled, onClick, ariaLabel }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-current={active ? 'page' : undefined}
      className={`min-w-[32px] h-8 px-2.5 rounded-[7px] text-xs font-semibold border transition-colors cursor-pointer inline-flex items-center justify-center ${
        active
          ? 'bg-accent-gold text-deep border-accent-gold'
          : disabled
            ? 'bg-card text-foreground-muted border-white/6 opacity-40 cursor-not-allowed'
            : 'bg-card text-foreground-muted border-white/6 hover:text-foreground hover:border-white/15'
      }`}
    >
      {children}
    </button>
  )
}

export default function Pagination({ page, pageCount, onPageChange }) {
  if (!pageCount || pageCount <= 1) return null
  const pages = buildPages(page, pageCount)

  return (
    <nav className="flex justify-center items-center gap-1.5 mt-5" aria-label="Pagination">
      <Btn
        ariaLabel="Previous page"
        disabled={page <= 1}
        onClick={() => page > 1 && onPageChange(page - 1)}
      >
        ‹ Prev
      </Btn>

      {pages.map((p, idx) => {
        if (p === '…') {
          return (
            <span key={`ell-${idx}`} className="text-foreground-muted/70 px-1 text-xs">
              …
            </span>
          )
        }
        return (
          <Btn
            key={p}
            ariaLabel={`Page ${p}`}
            active={p === page}
            onClick={() => onPageChange(p)}
          >
            {p}
          </Btn>
        )
      })}

      <Btn
        ariaLabel="Next page"
        disabled={page >= pageCount}
        onClick={() => page < pageCount && onPageChange(page + 1)}
      >
        Next ›
      </Btn>
    </nav>
  )
}
