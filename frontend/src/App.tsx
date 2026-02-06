import { useEffect, useState } from 'react'
import { SDKProvider, useLaunchParams, useMainButton, useBackButton } from '@telegram-apps/sdk-react'
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
  const backButton = useBackButton()

  // Show back button on detail pages
  useEffect(() => {
    const isDetailPage = location.pathname.includes('/signal/') || location.pathname.includes('/trader/')

    if (isDetailPage) {
      backButton.show()
      const handleBack = () => navigate(-1)
      backButton.on('click', handleBack)
      return () => {
        backButton.off('click', handleBack)
        backButton.hide()
      }
    } else {
      backButton.hide()
    }
  }, [location, navigate, backButton])

  // Parse initial tab from URL params
  const params = new URLSearchParams(location.search)
  const initialTab = params.get('tab')
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
    <SDKProvider acceptCustomStyles>
      <AppRoot>
        <BrowserRouter>
          <AppContent />
        </BrowserRouter>
      </AppRoot>
    </SDKProvider>
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
      }
    }
  }
}
