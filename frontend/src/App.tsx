import type { ReactNode } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import type { Role } from './api'
import { useAuth } from './auth'
import AuditLog from './pages/AuditLog'
import Login from './pages/Login'
import MyBookings from './pages/MyBookings'
import Search from './pages/Search'
import Staff from './pages/Staff'

function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user } = useAuth()
  const location = useLocation()
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (!roles.includes(user.role)) return <Navigate to="/" replace />
  return <>{children}</>
}

export default function App() {
  const { user, logout } = useAuth()
  const isStaff = user?.role === 'staff' || user?.role === 'admin'
  return (
    <div className="shell">
      <header className="topbar">
        <Link to="/" className="brand">
          <span className="logo">W</span> WeBook
        </Link>
        <nav>
          <NavLink to="/" end>
            Book a room
          </NavLink>
          {user && <NavLink to="/bookings">{isStaff ? 'All bookings' : 'My bookings'}</NavLink>}
          {isStaff && <NavLink to="/staff">Front desk</NavLink>}
          {user?.role === 'admin' && <NavLink to="/audit">Audit log</NavLink>}
        </nav>
        <div className="who">
          {user ? (
            <>
              <span className="pill" data-role={user.role}>
                {user.full_name} · {user.role}
              </span>
              <button
                className="link"
                onClick={() => {
                  // A full reload to the home page, so the protected page being left
                  // does not redirect to /login with a "from" path.
                  logout()
                  window.location.assign('/')
                }}
              >
                Sign out
              </button>
            </>
          ) : (
            <NavLink to="/login">Sign in</NavLink>
          )}
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Search />} />
          <Route path="/login" element={<Login />} />
          <Route
            path="/bookings"
            element={
              <RequireRole roles={['guest', 'staff', 'admin']}>
                <MyBookings />
              </RequireRole>
            }
          />
          <Route
            path="/staff"
            element={
              <RequireRole roles={['staff', 'admin']}>
                <Staff />
              </RequireRole>
            }
          />
          <Route
            path="/audit"
            element={
              <RequireRole roles={['admin']}>
                <AuditLog />
              </RequireRole>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <footer>
        Django REST Framework + GraphQL (<a href="/api/graphql">GraphiQL</a>) on Postgres ·{' '}
        <a href="/api/docs">OpenAPI docs</a> ·{' '}
        <a href="https://github.com/darshpandya02/webook">Source</a>
      </footer>
    </div>
  )
}
