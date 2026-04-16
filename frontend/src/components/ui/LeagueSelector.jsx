export default function LeagueSelector({ leagues = [], selected, onChange }) {
  const tabs = [{ code: null, name: 'All Leagues' }, ...leagues]

  return (
    <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-hide" role="tablist" aria-label="League filter">
      {tabs.map((league) => {
        const isActive = selected === league.code
        return (
          <button
            key={league.code ?? 'all'}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(league.code)}
            className={`cc-pill whitespace-nowrap ${
              isActive ? 'cc-pill-active' : 'cc-pill-inactive'
            }`}
          >
            {league.name}
          </button>
        )
      })}
    </div>
  )
}
