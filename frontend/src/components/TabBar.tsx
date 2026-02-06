import { NavLink } from 'react-router-dom'

export function TabBar() {
  return (
    <nav className="tab-bar">
      <NavLink
        to="/signals"
        className={({ isActive }) => `tab-item ${isActive ? 'active' : ''}`}
      >
        <span className="tab-icon">📊</span>
        <span>Signals</span>
      </NavLink>
      <NavLink
        to="/traders"
        className={({ isActive }) => `tab-item ${isActive ? 'active' : ''}`}
      >
        <span className="tab-icon">👥</span>
        <span>Traders</span>
      </NavLink>
    </nav>
  )
}
