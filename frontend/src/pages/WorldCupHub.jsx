import { useState, useEffect } from 'react'
import { Globe, Timer, Trophy, GitBranch, BarChart3 } from 'lucide-react'
import { getWorldCupGroups, getWorldCupBracket, getWorldCupWinnerOdds } from '../services/api'
import GroupTable from '../components/worldcup/GroupTable'
import BracketView from '../components/worldcup/BracketView'
import LoadingSpinner from '../components/ui/LoadingSpinner'

const WC_START = new Date('2026-06-11T00:00:00')

function getCountdownDays() {
  const now = new Date()
  const diff = WC_START - now
  return Math.max(0, Math.floor(diff / (1000 * 60 * 60 * 24)))
}

const TABS = [
  { key: 'groups', label: 'Groups', icon: Globe },
  { key: 'bracket', label: 'Bracket', icon: GitBranch },
  { key: 'odds', label: 'Winner Odds', icon: BarChart3 },
]

export default function WorldCupHub() {
  const [groups, setGroups] = useState({})
  const [bracket, setBracket] = useState(null)
  const [winnerOdds, setWinnerOdds] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeTab, setActiveTab] = useState('groups')
  const daysLeft = getCountdownDays()

  useEffect(() => {
    setLoading(true)
    Promise.all([
      getWorldCupGroups(),
      getWorldCupBracket(),
      getWorldCupWinnerOdds(),
    ])
      .then(([groupsData, bracketData, oddsData]) => {
        setGroups(groupsData.groups || {})
        setBracket(bracketData)
        setWinnerOdds(oddsData.teams || [])
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  const groupLetters = Object.keys(groups).sort()

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-24 pb-12">
      {/* Hero countdown */}
      <div className="text-center mb-12">
        <div className="flex items-center justify-center gap-2 mb-3">
          <Trophy className="w-6 h-6 text-accent-gold" />
          <h1 className="text-display text-foreground">
            FIFA World Cup <span className="text-accent-gold">2026</span>
          </h1>
        </div>
        <p className="text-sm text-foreground-muted">
          June 11 - July 19, 2026 | United States, Canada, Mexico
        </p>

        <div className="mt-6 inline-flex items-center gap-4 cc-card-featured px-8 py-4">
          <Timer className="w-5 h-5 text-accent-gold" />
          <div className="text-left">
            <p className="text-4xl font-bold text-accent-gold text-tabular">{daysLeft}</p>
            <p className="text-xs text-foreground-muted uppercase tracking-wider">Days to kickoff</p>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-20">
          <LoadingSpinner size="lg" label="Loading tournament data" />
        </div>
      ) : error ? (
        <div className="cc-card p-8 text-center">
          <p className="text-accent-red">{error}</p>
        </div>
      ) : (
        <>
          {/* Pill Tab Navigation */}
          <div className="flex gap-2 mb-8 justify-center" role="tablist">
            {TABS.map((tab) => {
              const Icon = tab.icon
              return (
                <button
                  key={tab.key}
                  role="tab"
                  aria-selected={activeTab === tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`cc-pill flex items-center gap-2 ${
                    activeTab === tab.key ? 'cc-pill-active' : 'cc-pill-inactive'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  {tab.label}
                </button>
              )
            })}
          </div>

          {/* Group Stage */}
          {activeTab === 'groups' && (
            <div>
              <p className="text-sm text-foreground-muted mb-6 text-center">
                12 groups of 4 teams each. Top 2 from each group plus the best 8 third-placed teams advance.
              </p>
              {groupLetters.length === 0 ? (
                <div className="cc-card p-12 text-center">
                  <p className="text-foreground-muted">Group data not yet available.</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {groupLetters.map((letter) => {
                    const group = groups[letter]
                    const teams = (group.standings || []).map((s) => ({
                      team_name: s.team,
                      played: s.played,
                      won: s.won,
                      drawn: s.drawn,
                      lost: s.lost,
                      gf: s.goals_for,
                      ga: s.goals_against,
                      gd: s.goal_difference,
                      points: s.points,
                    }))
                    return (
                      <GroupTable key={letter} groupName={letter} teams={teams} />
                    )
                  })}
                </div>
              )}
            </div>
          )}

          {/* Knockout Bracket */}
          {activeTab === 'bracket' && (
            <div>
              {bracket && bracket.round_of_32 && bracket.round_of_32.length > 0 ? (
                <div>
                  <p className="text-sm text-foreground-muted mb-6 text-center">
                    Predicted group stage outcomes based on FIFA rankings. Updates as matches are completed.
                  </p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {bracket.round_of_32.map((entry) => (
                      <div key={entry.group} className="cc-card p-4">
                        <p className="cc-label mb-3">Group {entry.group}</p>
                        <div className="space-y-2">
                          <div className="flex items-center gap-3">
                            <span className="w-6 h-6 rounded-full bg-accent-gold/15 text-accent-gold text-xs flex items-center justify-center font-bold">
                              1
                            </span>
                            <span className="text-sm font-medium text-foreground">{entry.predicted_winner}</span>
                          </div>
                          <div className="flex items-center gap-3">
                            <span className="w-6 h-6 rounded-full bg-elevated text-foreground-muted text-xs flex items-center justify-center font-bold">
                              2
                            </span>
                            <span className="text-sm text-foreground-muted">{entry.predicted_runner_up}</span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                  {bracket.note && (
                    <p className="text-foreground-muted text-xs mt-6 text-center">{bracket.note}</p>
                  )}
                </div>
              ) : (
                <BracketView bracket={null} />
              )}
            </div>
          )}

          {/* Winner Odds */}
          {activeTab === 'odds' && (
            <div>
              <p className="text-sm text-foreground-muted mb-6 text-center">
                Tournament winner probabilities derived from FIFA ranking points.
              </p>
              {winnerOdds.length === 0 ? (
                <div className="cc-card p-12 text-center">
                  <p className="text-foreground-muted">Winner odds data not yet available.</p>
                </div>
              ) : (
                <div className="cc-card overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border bg-deep/50">
                          <th className="text-left px-4 py-3 cc-label w-12">#</th>
                          <th className="text-left px-4 py-3 cc-label">Team</th>
                          <th className="text-center px-4 py-3 cc-label">FIFA Rank</th>
                          <th className="text-center px-4 py-3 cc-label">Points</th>
                          <th className="text-right px-4 py-3 cc-label">Win Prob</th>
                          <th className="px-4 py-3 w-40"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {winnerOdds.map((team, i) => {
                          const maxProb = winnerOdds[0]?.win_probability || 1
                          const barWidth = team.win_probability != null
                            ? Math.max(2, (team.win_probability / maxProb) * 100)
                            : 2
                          return (
                            <tr
                              key={team.team_name}
                              className="border-b border-white/5 hover:bg-white/[0.03] transition-colors duration-200"
                            >
                              <td className="px-4 py-3 text-foreground-muted text-xs text-tabular">{i + 1}</td>
                              <td className="px-4 py-3 font-medium text-foreground">
                                {i < 3 && (
                                  <span className="inline-block w-2 h-2 rounded-full bg-accent-gold mr-2" />
                                )}
                                {team.team_name}
                              </td>
                              <td className="px-4 py-3 text-center text-foreground-muted text-tabular">
                                {team.fifa_rank}
                              </td>
                              <td className="px-4 py-3 text-center text-foreground-muted text-tabular text-xs">
                                {team.total_points?.toFixed(1)}
                              </td>
                              <td className="px-4 py-3 text-right text-tabular text-accent-gold font-semibold">
                                {team.win_probability != null ? `${(team.win_probability * 100).toFixed(2)}%` : '--'}
                              </td>
                              <td className="px-4 py-3">
                                <div className="w-full bg-elevated rounded-full h-1.5">
                                  <div
                                    className="bg-accent-gold h-1.5 rounded-full transition-all duration-300"
                                    style={{ width: `${barWidth}%` }}
                                  />
                                </div>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
