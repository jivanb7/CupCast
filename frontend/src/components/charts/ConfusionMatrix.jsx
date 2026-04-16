const LABELS = ['Home Win', 'Draw', 'Away Win']

export default function ConfusionMatrix({ matrix = [], labels = LABELS }) {
  if (!matrix || matrix.length === 0) return null

  const total = matrix.flat().reduce((a, b) => a + b, 0)
  const maxVal = Math.max(...matrix.flat())

  function getCellStyle(val, isDiagonal) {
    const intensity = maxVal > 0 ? val / maxVal : 0
    if (isDiagonal) {
      return {
        backgroundColor: `rgba(34, 197, 94, ${0.08 + intensity * 0.25})`,
        color: intensity > 0.3 ? '#22C55E' : '#94A3B8',
      }
    }
    return {
      backgroundColor: `rgba(239, 68, 68, ${intensity * 0.15})`,
      color: intensity > 0.3 ? '#EF4444' : '#94A3B8',
    }
  }

  return (
    <div className="overflow-x-auto">
      <table className="text-sm">
        <thead>
          <tr>
            <th className="p-3 text-foreground-muted text-xs" colSpan={2} rowSpan={2} />
            <th className="p-3 text-center cc-label" colSpan={3}>Predicted</th>
          </tr>
          <tr>
            {labels.map((l) => (
              <th key={l} className="p-3 text-center text-xs text-foreground-muted font-medium">{l}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, i) => (
            <tr key={i}>
              {i === 0 && (
                <td
                  className="p-3 cc-label text-center"
                  rowSpan={3}
                  style={{ writingMode: 'vertical-lr', transform: 'rotate(180deg)' }}
                >
                  Actual
                </td>
              )}
              <td className="p-3 text-xs text-foreground-muted font-medium text-right">{labels[i]}</td>
              {row.map((val, j) => (
                <td
                  key={j}
                  className="p-4 text-center rounded-btn"
                  style={getCellStyle(val, i === j)}
                >
                  <div className="font-bold text-tabular text-base">{val}</div>
                  <div className="text-xs opacity-60 mt-0.5 text-tabular">
                    {total > 0 ? `${Math.round(val / total * 100)}%` : '-'}
                  </div>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
