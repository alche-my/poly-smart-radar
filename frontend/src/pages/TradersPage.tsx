import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getTraders } from '../api/client'
import type { Trader } from '../api/types'

const TYPE_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'HUMAN', label: '👤 Human' },
  { value: 'ALGO', label: '🤖 Algo' },
  { value: 'MM', label: '📊 MM' },
]

function formatPnl(pnl: number): string {
  if (Math.abs(pnl) >= 1_000_000) {
    return `$${(pnl / 1_000_000).toFixed(1)}M`
  }
  if (Math.abs(pnl) >= 1_000) {
    return `$${(pnl / 1_000).toFixed(0)}K`
  }
  return `$${pnl.toFixed(0)}`
}

export function TradersPage() {
  const navigate = useNavigate()
  const [traders, setTraders] = useState<Trader[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [traderType, setTraderType] = useState('')

  useEffect(() => {
    async function loadTraders() {
      setLoading(true)
      setError(null)

      try {
        const response = await getTraders({
          trader_type: traderType || undefined,
          sort_by: 'trader_score',
          sort_order: 'desc',
          page_size: 50,
        })
        setTraders(response.traders)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load traders')
      } finally {
        setLoading(false)
      }
    }

    loadTraders()
  }, [traderType])

  return (
    <div>
      <h1 className="page-header">👥 Traders</h1>

      {/* Type filters */}
      <div className="filters">
        {TYPE_OPTIONS.map(opt => (
          <button
            key={opt.value}
            className={`filter-chip ${traderType === opt.value ? 'active' : ''}`}
            onClick={() => setTraderType(opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Content */}
      {loading && (
        <div className="empty-state">
          <div className="empty-icon">⏳</div>
          <div>Loading traders...</div>
        </div>
      )}

      {error && (
        <div className="empty-state">
          <div className="empty-icon">❌</div>
          <div>{error}</div>
        </div>
      )}

      {!loading && !error && traders.length === 0 && (
        <div className="empty-state">
          <div className="empty-icon">📭</div>
          <div>No traders found</div>
        </div>
      )}

      {!loading && !error && traders.map((trader, idx) => (
        <div
          key={trader.wallet_address}
          className="signal-card"
          onClick={() => navigate(`/trader/${trader.wallet_address}`)}
        >
          <div className="signal-header">
            <div className="signal-tier">
              <span style={{ opacity: 0.6 }}>#{idx + 1}</span>
              <span>
                {trader.trader_type === 'HUMAN' ? '👤' : trader.trader_type === 'ALGO' ? '🤖' : '📊'}
              </span>
              <span>{trader.username || trader.wallet_address.slice(0, 8)}</span>
            </div>
            <div className="signal-score">
              Score: {trader.trader_score.toFixed(1)}
            </div>
          </div>

          <div className="signal-meta">
            <div>
              WR: {(trader.win_rate * 100).toFixed(0)}% • PnL: {formatPnl(trader.pnl)}
            </div>
            <div>
              {trader.total_closed} trades
            </div>
          </div>

          {trader.domain_tags.length > 0 && (
            <div className="signal-traders" style={{ marginTop: 8 }}>
              {trader.domain_tags.slice(0, 3).map(tag => (
                <span key={tag} className="trader-chip" style={{ background: '#8e8e93' }}>
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
