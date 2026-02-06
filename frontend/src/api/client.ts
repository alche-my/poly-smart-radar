import type { SignalListResponse, TraderListResponse, Signal, Trader } from './types'

// API base URL - will be configured for production
const API_BASE = import.meta.env.VITE_API_URL || '/api'

// Get initData for authentication
function getInitData(): string {
  return window.Telegram?.WebApp?.initData || ''
}

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const initData = getInitData()

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }

  // Add Telegram auth if available
  if (initData) {
    headers['Authorization'] = `tma ${initData}`
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...headers,
      ...options?.headers,
    },
  })

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`)
  }

  return response.json()
}

// Signals API
export async function getSignals(params?: {
  tier?: number
  status?: string
  trader_type?: string
  page?: number
  page_size?: number
}): Promise<SignalListResponse> {
  const searchParams = new URLSearchParams()

  if (params?.tier) searchParams.set('tier', String(params.tier))
  if (params?.status) searchParams.set('status', params.status)
  if (params?.trader_type) searchParams.set('trader_type', params.trader_type)
  if (params?.page) searchParams.set('page', String(params.page))
  if (params?.page_size) searchParams.set('page_size', String(params.page_size))

  const query = searchParams.toString()
  return fetchApi<SignalListResponse>(`/signals${query ? `?${query}` : ''}`)
}

export async function getSignal(id: number): Promise<Signal> {
  return fetchApi<Signal>(`/signals/${id}`)
}

// Traders API
export async function getTraders(params?: {
  trader_type?: string
  min_score?: number
  sort_by?: string
  sort_order?: string
  page?: number
  page_size?: number
}): Promise<TraderListResponse> {
  const searchParams = new URLSearchParams()

  if (params?.trader_type) searchParams.set('trader_type', params.trader_type)
  if (params?.min_score) searchParams.set('min_score', String(params.min_score))
  if (params?.sort_by) searchParams.set('sort_by', params.sort_by)
  if (params?.sort_order) searchParams.set('sort_order', params.sort_order)
  if (params?.page) searchParams.set('page', String(params.page))
  if (params?.page_size) searchParams.set('page_size', String(params.page_size))

  const query = searchParams.toString()
  return fetchApi<TraderListResponse>(`/traders${query ? `?${query}` : ''}`)
}

export async function getTrader(wallet: string): Promise<Trader> {
  return fetchApi<Trader>(`/traders/${wallet}`)
}

export async function getTraderSignals(wallet: string): Promise<{ signals: Signal[] }> {
  return fetchApi<{ signals: Signal[] }>(`/traders/${wallet}/signals`)
}
