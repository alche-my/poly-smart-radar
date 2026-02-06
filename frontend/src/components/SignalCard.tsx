import { useNavigate } from 'react-router-dom'
import type { Signal } from '../api/types'

const TIER_EMOJI: Record<number, string> = {
  1: '🔴',
  2: '🟡',
  3: '🔵',
}

function formatTimeAgo(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)

  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`

  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}h ago`

  const diffDays = Math.floor(diffHours / 24)
  return `${diffDays}d ago`
}

interface SignalCardProps {
  signal: Signal
}

export function SignalCard({ signal }: SignalCardProps) {
  const navigate = useNavigate()

  const humanTraders = signal.traders_involved.filter(t => t.trader_type === 'HUMAN')
  const algoTraders = signal.traders_involved.filter(t => t.trader_type === 'ALGO')

  const handleClick = () => {
    navigate(`/signal/${signal.id}`)
  }

  return (
    <div className="signal-card" onClick={handleClick}>
      <div className="signal-header">
        <div className="signal-tier">
          <span>{TIER_EMOJI[signal.tier] || '⚪'}</span>
          <span>TIER {signal.tier}</span>
          {signal.status !== 'ACTIVE' && (
            <span style={{ color: signal.status === 'CLOSED' ? '#ff3b30' : '#ff9500' }}>
              • {signal.status}
            </span>
          )}
        </div>
        <div className="signal-score">
          Score: {signal.signal_score.toFixed(1)}
        </div>
      </div>

      <div className="signal-title">{signal.market_title}</div>

      <div className="signal-meta">
        <div className="signal-direction">
          <span>{signal.direction}</span>
          <span>@ ${signal.current_price.toFixed(2)}</span>
        </div>
        <div className="signal-time">
          {formatTimeAgo(signal.created_at)}
        </div>
      </div>

      <div className="signal-traders" style={{ marginTop: 8 }}>
        {humanTraders.length > 0 && (
          <span className="trader-chip human">
            👤 {humanTraders.length} HUMAN
          </span>
        )}
        {algoTraders.length > 0 && (
          <span className="trader-chip algo">
            🤖 {algoTraders.length} ALGO
          </span>
        )}
      </div>
    </div>
  )
}
