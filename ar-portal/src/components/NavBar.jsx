import { useNavigate } from 'react-router-dom'
import './NavBar.css'

const MailIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"
       strokeLinecap="round" strokeLinejoin="round">
    <rect x="2" y="4" width="20" height="16" rx="2"/>
    <polyline points="2,4 12,13 22,4"/>
  </svg>
)

export default function NavBar({ userName = 'Agamjot Kaur' }) {
  const navigate = useNavigate()
  const initials = userName.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase()

  return (
    <header className="nav-bar">
      <div className="nav-inner">
        <a className="nav-brand" onClick={() => navigate('/dashboard')} style={{ cursor: 'pointer' }}>
          <div className="nav-brand-icon" aria-hidden="true">
            <MailIcon />
          </div>
          <span className="nav-wordmark">AR Portal</span>
        </a>
        <div className="nav-user">
          <div className="nav-avatar" aria-hidden="true">{initials}</div>
          <span className="nav-user-name">{userName}</span>
        </div>
      </div>
    </header>
  )
}
