import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getTrader, getTraderSignals } from '../api/client'
import { SignalCard } from '../components/SignalCard'
import type { Trader, Signal } from '../api/types'

function formatPnl(pnl: number): string {
  if (Math.abs(pnl) >= 1_000_000) {
    return `$${(pnl / 1_000_000).toFixed(1)}M`
  }
  if (Math.abs(pnl) >= 1_000) {
    return `$${(pnl / 1_000).toFixed(0)}K`
  }
  return `$${pnl.toFixed(0)}`
}

export function TraderDetailPage() {
  const { wallet } = useParams<{ wallet: string }>()
  const [trader, setTrader] = useState<Trader | null>(null)
  const [signals, setSignals] = useState<Signal[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      if (!wallet) return

      setLoading(true)
      try {
        const [traderData, signalsData] = await Promise.all([
          getTrader(wallet),
          getTraderSignals(wallet),
        ])
        setTrader(traderData)
        setSignals(signalsData.signals)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load trader')
      } finally {
        setLoading(false)
      }
    }

    load()
  }, [wallet])

  if (loading) {
    return (
      <div className="empty-state">
        <div className="empty-icon">⏳</div>
        <div>Loading...</div>
      </div>
    )
  }

  if (error || !trader) {
    return (
      <div className="empty-state">
        <div className="empty-icon">❌</div>
        <div>{error || 'Trader not found'}</div>
      </div>
    )
  }

  const typeIcon = trader.trader_type === 'HUMAN' ? '👤' :
                   trader.trader_type === 'ALGO' ? '🤖' : '📊'

  return (
    <div>
      {/* Profile Card */}
      <div className="signal-card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
          <div style={{ fontSize: 36 }}>{typeIcon}</div>
          <div>
            <div style={{ fontSize: 18, fontWeight: 600 }}>
              {trader.username || trader.wallet_address.slice(0, 12)}
            </div>
            <div style={{ fontSize: 13, color: 'var(--tg-theme-hint-color, #999)' }}>
              {trader.trader_type} • Score: {trader.trader_score.toFixed(1)}
            </div>
          </div>
        </div>

        {/* Stats Grid */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, 1fr)',
          gap: 12,
          marginTop: 16,
        }}>
          <div style={{ textAlign: 'center', padding: 12, background: 'var(--tg-theme-bg-color, #fff)', borderRadius: 8 }}>
            <div style={{ fontSize: 20, fontWeight: 600 }}>
              {(trader.win_rate * 100).toFixed(0)}%
            </div>
            <div style={{ fontSize: 12, color: 'var(--tg-theme-hint-color, #999)' }}>
              Win Rate
            </div>
          </div>
          <div style={{ textAlign: 'center', padding: 12, background: 'var(--tg-theme-bg-color, #fff)', borderRadius: 8 }}>
            <div style={{ fontSize: 20, fontWeight: 600, color: trader.pnl >= 0 ? '#34c759' : '#ff3b30' }}>
              {formatPnl(trader.pnl)}
            </div>
            <div style={{ fontSize: 12, color: 'var(--tg-theme-hint-color, #999)' }}>
              Total PnL
            </div>
          </div>
          <div style={{ textAlign: 'center', padding: 12, background: 'var(--tg-theme-bg-color, #fff)', borderRadius: 8 }}>
            <div style={{ fontSize: 20, fontWeight: 600 }}>
              {trader.total_closed}
            </div>
            <div style={{ fontSize: 12, color: 'var(--tg-theme-hint-color, #999)' }}>
              Closed Trades
            </div>
          </div>
          <div style={{ textAlign: 'center', padding: 12, background: 'var(--tg-theme-bg-color, #fff)', borderRadius: 8 }}>
            <div style={{ fontSize: 20, fontWeight: 600 }}>
              {trader.timing_quality?.toFixed(2) || '-'}
            </div>
            <div style={{ fontSize: 12, color: 'var(--tg-theme-hint-color, #999)' }}>
              Timing Quality
            </div>
          </div>
        </div>

        {/* Domain Tags */}
        {trader.domain_tags.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Specializations</div>
            <div className="signal-traders">
              {trader.domain_tags.map(tag => (
                <span key={tag} className="trader-chip" style={{ background: '#8e8e93' }}>
                  {tag}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Polymarket Link */}
        <a
          href={`https://polymarket.com/profile/${trader.wallet_address}`}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'block',
            marginTop: 16,
            padding: '10px 16px',
            background: 'var(--tg-theme-button-color, #3390ec)',
            color: 'var(--tg-theme-button-text-color, #fff)',
            borderRadius: 8,
            textAlign: 'center',
            textDecoration: 'none',
            fontWeight: 500,
          }}
        >
          View on Polymarket →
        </a>
      </div>

      {/* Recent Bets */}
      {trader.recent_bets.length > 0 && (
        <>
          <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
            📈 Recent Bets
          </h3>
          {trader.recent_bets.slice(0, 5).map((bet, idx) => (
            <div key={idx} className="signal-card">
              <div className="signal-title" style={{ fontSize: 14 }}>
                {bet.pnl > 0 ? '✅' : bet.pnl < 0 ? '❌' : '➖'} {bet.title}
              </div>
              <div className="signal-meta">
                <div style={{ color: bet.pnl >= 0 ? '#34c759' : '#ff3b30' }}>
                  {bet.pnl >= 0 ? '+' : ''}{formatPnl(bet.pnl)}
                </div>
                {bet.category && bet.category.length > 0 && (
                  <div>{bet.category.join(', ')}</div>
                )}
              </div>
            </div>
          ))}
        </>
      )}

      {/* Signals */}
      {signals.length > 0 && (
        <>
          <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, marginTop: 16 }}>
            📊 Signals
          </h3>
          {signals.map(signal => (
            <SignalCard key={signal.id} signal={signal} />
          ))}
        </>
      )}
    </div>
  )
}
