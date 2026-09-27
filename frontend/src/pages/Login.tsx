import { useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'

const DEMO = [
  { username: 'guest', password: 'webook-guest', role: 'Guest', can: 'Search, book, cancel, order room service for own stays' },
  { username: 'staff', password: 'webook-staff', role: 'Staff', can: 'Front desk: every booking, check-in, check-out and bill, room service' },
  { username: 'admin', password: 'webook-admin', role: 'Admin', can: 'Everything staff can do, plus catalogue edits and the audit log' },
]

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent, u = username, p = password) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const user = await login(u, p)
      const from = (location.state as { from?: string } | null)?.from
      navigate(from ?? (user.role === 'guest' ? '/' : '/staff'), { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="login">
      <form className="card" onSubmit={submit}>
        <h1>Sign in</h1>
        <label>
          Username
          <input name="username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        </label>
        <label>
          Password
          <input
            name="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={busy}>
          {busy ? 'Signing in...' : 'Sign in'}
        </button>
      </form>

      <div className="card demo">
        <h2>Demo accounts</h2>
        <p className="muted">Shared demo data, restored every night. Click a row to sign in.</p>
        <table>
          <thead>
            <tr>
              <th>Role</th>
              <th>Username</th>
              <th>Password</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {DEMO.map((d) => (
              <tr key={d.username}>
                <td>
                  <strong>{d.role}</strong>
                  <div className="muted small">{d.can}</div>
                </td>
                <td>
                  <code>{d.username}</code>
                </td>
                <td>
                  <code>{d.password}</code>
                </td>
                <td>
                  <button
                    className="secondary"
                    data-testid={`demo-${d.username}`}
                    disabled={busy}
                    onClick={(e) => {
                      setUsername(d.username)
                      setPassword(d.password)
                      void submit(e as unknown as FormEvent, d.username, d.password)
                    }}
                  >
                    Use
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
