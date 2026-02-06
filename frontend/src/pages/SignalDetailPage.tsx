import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getSignal } from '../api/client'
import type { Signal } from '../api/types'

const TIER_EMOJI: Record<number, string> = {
  1: '🔴',
  2: '🟡',
  3: '🔵',
}

function formatPnl(pnl: number): string {
  if (Math.abs(pnl) >= 1_000_000) {
    return `$${(pnl / 1_000_000).toFixed(1)}M`
  }
  if (Math.abs(pnl) >= 1_000) {
    return `$${(pnl / 1_000).toFixed(0)}K`
  }
  return `$${pnl.toFixed(0)}`
}

export function SignalDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [signal, setSignal] = useState<Signal | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      if (!id) return

      setLoading(true)
      try {
        const data = await getSignal(Number(id))
        setSignal(data)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load signal')
      } finally {
        setLoading(false)
      }
    }

    load()
  }, [id])

  if (loading) {
    return (
      <div className="empty-state">
        <div className="empty-icon">⏳</div>
        <div>Loading...</div>
      </div>
    )
  }

  if (error || !signal) {
    return (
      <div className="empty-state">
        <div className="empty-icon">❌</div>
        <div>{error || 'Signal not found'}</div>
      </div>
    )
  }

  const humanTraders = signal.traders_involved.filter(t => t.trader_type === 'HUMAN')
  const algoTraders = signal.traders_involved.filter(t => t.trader_type === 'ALGO')

  return (
    <div>
      {/* Header */}
      <div className="signal-card" style={{ marginBottom: 16 }}>
        <div className="signal-header">
          <div className="signal-tier">
            <span>{TIER_EMOJI[signal.tier]}</span>
            <span>TIER {signal.tier}</span>
            <span style={{
              color: signal.status === 'ACTIVE' ? '#34c759' :
                     signal.status === 'WEAKENING' ? '#ff9500' : '#ff3b30'
            }}>
              • {signal.status}
            </span>
          </div>
          <div className="signal-score">
            Score: {signal.signal_score.toFixed(1)}
          </div>
        </div>

        <h2 style={{ fontSize: 18, fontWeight: 600, margin: '12px 0' }}>
          {signal.market_title}
        </h2>

        <div className="signal-meta">
          <div className="signal-direction">
            Direction: <strong>{signal.direction}</strong> @ ${signal.current_price.toFixed(2)}
          </div>
        </div>

        {signal.market_slug && (
          <a
            href={`https://polymarket.com/event/${signal.market_slug}`}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'block',
              marginTop: 12,
              padding: '10px 16px',
              background: 'var(--tg-theme-button-color, #3390ec)',
              color: 'var(--tg-theme-button-text-color, #fff)',
              borderRadius: 8,
              textAlign: 'center',
              textDecoration: 'none',
              fontWeight: 500,
            }}
          >
            Open on Polymarket →
          </a>
        )}
      </div>

      {/* Human Traders */}
      {humanTraders.length > 0 && (
        <>
          <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
            👤 Human Traders ({humanTraders.length})
          </h3>
          {humanTraders.map(trader => (
            <div
              key={trader.wallet_address}
              className="signal-card"
              onClick={() => navigate(`/trader/${trader.wallet_address}`)}
            >
              <div className="signal-header">
                <div className="signal-tier">
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
                  {trader.change_type} ${trader.size.toFixed(0)}
                </div>
              </div>
            </div>
          ))}
        </>
      )}

      {/* Algo Traders */}
      {algoTraders.length > 0 && (
        <>
          <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, marginTop: 16 }}>
            🤖 Algo Traders ({algoTraders.length})
          </h3>
          {algoTraders.map(trader => (
            <div
              key={trader.wallet_address}
              className="signal-card"
              onClick={() => navigate(`/trader/${trader.wallet_address}`)}
            >
              <div className="signal-header">
                <div className="signal-tier">
                  <span>{trader.username || trader.wallet_address.slice(0, 8)}</span>
                </div>
                <div className="signal-score">
                  {trader.change_type} ${trader.size.toFixed(0)}
                </div>
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  )
}
