export default function GroupTable({ groupName, teams = [] }) {
  return (
    <div className="cc-card p-4 overflow-hidden">
      <h3 className="text-sm font-semibold text-accent-gold mb-3 flex items-center gap-2">
        <span className="w-6 h-6 rounded-full bg-accent-gold/10 flex items-center justify-center text-xs font-bold text-accent-gold">
          {groupName}
        </span>
        Group {groupName}
      </h3>

      {teams.length === 0 ? (
        <p className="text-foreground-muted text-xs py-4 text-center">No teams assigned yet.</p>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-foreground-muted border-b border-border/50">
              <th className="text-left py-2 pl-2">Team</th>
              <th className="text-center w-7 py-2">P</th>
              <th className="text-center w-7 py-2">W</th>
              <th className="text-center w-7 py-2">D</th>
              <th className="text-center w-7 py-2">L</th>
              <th className="text-center w-9 py-2">GD</th>
              <th className="text-center w-9 py-2 font-bold text-foreground">Pts</th>
            </tr>
          </thead>
          <tbody>
            {teams.map((team, i) => {
              const isQualified = i < 2
              const isMaybeQualified = i === 2
              return (
                <tr
                  key={team.team_name}
                  className={`border-t border-white/5 transition-colors duration-200 hover:bg-white/[0.03] ${
                    i % 2 === 0 ? '' : 'bg-white/[0.015]'
                  }`}
                >
                  <td className="py-2 pl-2">
                    <div className="flex items-center gap-2">
                      {isQualified && (
                        <span className="w-1 h-4 rounded-sm bg-accent-gold" />
                      )}
                      {isMaybeQualified && (
                        <span className="w-1 h-4 rounded-sm bg-accent-amber/40" />
                      )}
                      {!isQualified && !isMaybeQualified && (
                        <span className="w-1 h-4" />
                      )}
                      <span className={`truncate ${
                        isQualified ? 'text-foreground font-medium' :
                        isMaybeQualified ? 'text-foreground-muted' :
                        'text-foreground-muted/60'
                      }`}>
                        {team.team_name}
                      </span>
                    </div>
                  </td>
                  <td className="text-center text-foreground-muted text-tabular">{team.played}</td>
                  <td className="text-center text-foreground-muted text-tabular">{team.won}</td>
                  <td className="text-center text-foreground-muted text-tabular">{team.drawn}</td>
                  <td className="text-center text-foreground-muted text-tabular">{team.lost}</td>
                  <td className={`text-center text-tabular ${
                    team.gd > 0 ? 'text-accent-green' : team.gd < 0 ? 'text-accent-red' : 'text-foreground-muted'
                  }`}>
                    {team.gd > 0 ? `+${team.gd}` : team.gd}
                  </td>
                  <td className={`text-center font-bold text-tabular ${
                    isQualified ? 'text-foreground' : 'text-foreground-muted'
                  }`}>
                    {team.points}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
