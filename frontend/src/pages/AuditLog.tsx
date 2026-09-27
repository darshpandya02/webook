import { useEffect, useState } from 'react'
import { api, type AuditRow } from '../api'

export default function AuditLog() {
  const [rows, setRows] = useState<AuditRow[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    api.audit().then((r) => setRows(r.results), (e) => setError(e.message))
  }, [])
  return (
    <section>
      <h1>Audit log</h1>
      <p className="muted">Every booking command, written in the same transaction as the change it records. Rejected commands are logged too.</p>
      {error && <p className="error banner">{error}</p>}
      {rows && (
        <div className="card">
          <table className="audit">
            <thead>
              <tr>
                <th>When</th>
                <th>Command</th>
                <th>Actor</th>
                <th>Booking</th>
                <th>Outcome</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={r.outcome}>
                  <td className="small">{new Date(r.created_at).toLocaleString()}</td>
                  <td>
                    <code>{r.command}</code>
                  </td>
                  <td>{r.actor ?? '-'}</td>
                  <td>{r.booking ?? '-'}</td>
                  <td>{r.outcome}</td>
                  <td className="small">
                    <code>{JSON.stringify(r.detail)}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
