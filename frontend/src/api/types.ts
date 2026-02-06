export interface TraderBrief {
  wallet_address: string
  username: string | null
  trader_type: 'HUMAN' | 'ALGO' | 'MM'
  trader_score: number
  win_rate: number
  pnl: number
  conviction: number
  change_type: string
  size: number
  detected_at: string | null
}

export interface Signal {
  id: number
  condition_id: string
  market_title: string
  market_slug: string | null
  direction: 'YES' | 'NO'
  signal_score: number
  peak_score: number
  tier: 1 | 2 | 3
  status: 'ACTIVE' | 'WEAKENING' | 'CLOSED'
  current_price: number
  traders_involved: TraderBrief[]
  created_at: string
  updated_at: string
}

export interface SignalListResponse {
  signals: Signal[]
  total: number
  page: number
  page_size: number
}

export interface Trader {
  wallet_address: string
  username: string | null
  trader_type: 'HUMAN' | 'ALGO' | 'MM'
  trader_score: number
  win_rate: number
  pnl: number
  total_closed: number
  timing_quality: number | null
  domain_tags: string[]
  algo_signals: string[]
  category_scores: Record<string, number>
  recent_bets: Array<{
    title: string
    pnl: number
    category?: string[]
  }>
  created_at: string | null
  updated_at: string | null
}

export interface TraderListResponse {
  traders: Trader[]
  total: number
  page: number
  page_size: number
}
