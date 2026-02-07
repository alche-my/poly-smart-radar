import { useEffect, useState } from 'react'
import { AppRoot } from '@telegram-apps/telegram-ui'
import { BrowserRouter, Routes, Route, useNavigate, useLocation } from 'react-router-dom'

import { SignalsPage } from './pages/SignalsPage'
import { TradersPage } from './pages/TradersPage'
import { SignalDetailPage } from './pages/SignalDetailPage'
import { TraderDetailPage } from './pages/TraderDetailPage'
import { TabBar } from './components/TabBar'

import '@telegram-apps/telegram-ui/dist/styles.css'

function AppContent() {
  const location = useLocation()
  const navigate = useNavigate()

  // Handle Telegram back button on detail pages
  useEffect(() => {
    const webapp = window.Telegram?.WebApp
    if (!webapp) return

    const isDetailPage = location.pathname.includes('/signal/') || location.pathname.includes('/trader/')

    if (isDetailPage) {
      webapp.BackButton?.show()
      const handleBack = () => navigate(-1)
      webapp.BackButton?.onClick(handleBack)
      return () => {
        webapp.BackButton?.offClick(handleBack)
        webapp.BackButton?.hide()
      }
    } else {
      webapp.BackButton?.hide()
    }
  }, [location, navigate])

  // Parse tier filter from URL params
  const params = new URLSearchParams(location.search)
  const tierFilter = params.get('tier')

  return (
    <div className="app">
      <main className="app-content">
        <Routes>
          <Route path="/" element={<SignalsPage tierFilter={tierFilter} />} />
          <Route path="/signals" element={<SignalsPage tierFilter={tierFilter} />} />
          <Route path="/signal/:id" element={<SignalDetailPage />} />
          <Route path="/traders" element={<TradersPage />} />
          <Route path="/trader/:wallet" element={<TraderDetailPage />} />
        </Routes>
      </main>
      <TabBar />
    </div>
  )
}

export function App() {
  const [ready, setReady] = useState(false)

  useEffect(() => {
    // Wait for Telegram WebApp to be ready
    if (window.Telegram?.WebApp) {
      window.Telegram.WebApp.ready()
      window.Telegram.WebApp.expand()
      setReady(true)
    } else {
      // Development mode without Telegram
      setReady(true)
    }
  }, [])

  if (!ready) {
    return <div className="loading">Loading...</div>
  }

  return (
    <AppRoot>
      <BrowserRouter>
        <AppContent />
      </BrowserRouter>
    </AppRoot>
  )
}

// Extend Window interface for Telegram
declare global {
  interface Window {
    Telegram?: {
      WebApp: {
        ready: () => void
        expand: () => void
        close: () => void
        initData: string
        initDataUnsafe: {
          user?: {
            id: number
            first_name: string
            last_name?: string
            username?: string
          }
        }
        BackButton?: {
          show: () => void
          hide: () => void
          onClick: (callback: () => void) => void
          offClick: (callback: () => void) => void
        }
      }
    }
  }
}
