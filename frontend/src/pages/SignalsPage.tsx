import { useEffect, useState } from 'react'
import { SignalCard } from '../components/SignalCard'
import { getSignals } from '../api/client'
import type { Signal } from '../api/types'

interface SignalsPageProps {
  tierFilter?: string | null
}

const TIER_OPTIONS = [
  { value: '', label: 'All' },
  { value: '1', label: '🔴 Tier 1' },
  { value: '2', label: '🟡 Tier 2' },
  { value: '3', label: '🔵 Tier 3' },
]

const STATUS_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'ACTIVE', label: 'Active' },
  { value: 'WEAKENING', label: 'Weakening' },
  { value: 'CLOSED', label: 'Closed' },
]

export function SignalsPage({ tierFilter }: SignalsPageProps) {
  const [signals, setSignals] = useState<Signal[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tier, setTier] = useState(tierFilter || '')
  const [status, setStatus] = useState('ACTIVE')

  useEffect(() => {
    async function loadSignals() {
      setLoading(true)
      setError(null)

      try {
        const response = await getSignals({
          tier: tier ? Number(tier) : undefined,
          status: status || undefined,
          page_size: 50,
        })
        setSignals(response.signals)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load signals')
      } finally {
        setLoading(false)
      }
    }

    loadSignals()
  }, [tier, status])

  return (
    <div>
      <h1 className="page-header">📊 Signals</h1>

      {/* Tier filters */}
      <div className="filters">
        {TIER_OPTIONS.map(opt => (
          <button
            key={opt.value}
            className={`filter-chip ${tier === opt.value ? 'active' : ''}`}
            onClick={() => setTier(opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Status filters */}
      <div className="filters">
        {STATUS_OPTIONS.map(opt => (
          <button
            key={opt.value}
            className={`filter-chip ${status === opt.value ? 'active' : ''}`}
            onClick={() => setStatus(opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Content */}
      {loading && (
        <div className="empty-state">
          <div className="empty-icon">⏳</div>
          <div>Loading signals...</div>
        </div>
      )}

      {error && (
        <div className="empty-state">
          <div className="empty-icon">❌</div>
          <div>{error}</div>
        </div>
      )}

      {!loading && !error && signals.length === 0 && (
        <div className="empty-state">
          <div className="empty-icon">📭</div>
          <div>No signals found</div>
        </div>
      )}

      {!loading && !error && signals.map(signal => (
        <SignalCard key={signal.id} signal={signal} />
      ))}
    </div>
  )
}
