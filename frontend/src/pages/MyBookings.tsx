import { useCallback, useEffect, useState } from 'react'
import { api, type Booking, type Item, type Status } from '../api'
import { useAuth } from '../auth'
import BookingCard from './BookingCard'

const FILTERS: { label: string; value: '' | Status }[] = [
  { label: 'All', value: '' },
  { label: 'Confirmed', value: 'confirmed' },
  { label: 'Checked in', value: 'checked_in' },
  { label: 'Checked out', value: 'checked_out' },
  { label: 'Cancelled', value: 'cancelled' },
]

export default function MyBookings() {
  const { user } = useAuth()
  const isStaff = user?.role !== 'guest'
  const [bookings, setBookings] = useState<Booking[] | null>(null)
  const [items, setItems] = useState<Item[]>([])
  const [filter, setFilter] = useState<'' | Status>('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const r = await api.bookings(filter ? `?status=${filter}&limit=100` : '?limit=100')
      setBookings(r.results)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load bookings')
    }
  }, [filter])

  useEffect(() => {
    void load()
  }, [load])
  useEffect(() => {
    api.items().then((all) => setItems(all.filter((i) => i.is_available)), () => setItems([]))
  }, [])

  async function act(fn: () => Promise<unknown>) {
    setBusy(true)
    setError('')
    try {
      await fn()
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <div className="row">
        <h1>{isStaff ? 'All bookings' : 'My bookings'}</h1>
        <div className="tabs">
          {FILTERS.map((f) => (
            <button key={f.value} className={filter === f.value ? 'tab active' : 'tab'} onClick={() => setFilter(f.value)}>
              {f.label}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="error banner" role="alert">{error}</p>}
      {bookings === null ? (
        <p className="muted">Loading...</p>
      ) : bookings.length === 0 ? (
        <p className="muted">No bookings yet.</p>
      ) : (
        <div className="list">
          {bookings.map((b) => (
            <BookingCard
              key={b.id}
              booking={b}
              items={items}
              showGuest={isStaff}
              busy={busy}
              onRoomService={(item, qty) => act(() => api.roomService(b.id, item, qty))}
              actions={
                b.status === 'confirmed'
                  ? [{ label: 'Cancel', kind: 'danger', testId: `cancel-${b.id}`, onClick: () => act(() => api.cancel(b.id)) }]
                  : []
              }
            />
          ))}
        </div>
      )}
    </section>
  )
}
