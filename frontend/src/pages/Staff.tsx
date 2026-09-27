import { useCallback, useEffect, useState } from 'react'
import { api, money, prettyDate, type Booking, type Item, type Occupancy } from '../api'
import BookingCard, { Bill } from './BookingCard'

export default function Staff() {
  const [data, setData] = useState<Occupancy | null>(null)
  const [items, setItems] = useState<Item[]>([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [lastBill, setLastBill] = useState<Booking | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setData(await api.occupancy())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the dashboard')
    }
  }, [])

  useEffect(() => {
    void load()
    api.items().then((all) => setItems(all.filter((i) => i.is_available)), () => setItems([]))
  }, [load])

  async function act(fn: () => Promise<Booking>, message: (b: Booking) => string) {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const b = await fn()
      setNotice(message(b))
      if (b.status === 'checked_out') setLastBill(b)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed')
    } finally {
      setBusy(false)
    }
  }

  if (!data) return <p className="muted">{error || 'Loading...'}</p>
  const peak = Math.max(1, ...data.series.map((d) => d.occupied))

  return (
    <section>
      <h1>Front desk · {prettyDate(data.date)}</h1>
      {error && <p className="error banner" role="alert">{error}</p>}
      {notice && <p className="success banner" role="status">{notice}</p>}

      <div className="stats">
        <div className="card stat">
          <span className="muted small">Occupancy tonight</span>
          <span className="big" data-testid="occupancy-rate">
            {Math.round(data.occupancy_rate * 100)}%
          </span>
          <span className="small">
            {data.occupied} of {data.rooms_total} rooms
          </span>
        </div>
        <div className="card stat">
          <span className="muted small">Arrivals today</span>
          <span className="big">{data.arrivals.length}</span>
        </div>
        <div className="card stat">
          <span className="muted small">Due out</span>
          <span className="big">{data.departures.length}</span>
        </div>
        <div className="card stat">
          <span className="muted small">In house</span>
          <span className="big">{data.in_house.length}</span>
        </div>
      </div>

      <div className="card">
        <h2>Next 7 nights</h2>
        <div className="bars" role="img" aria-label="Rooms occupied per night for the next 7 nights">
          {data.series.map((d) => (
            <div key={d.date} className="bar">
              <span className="small">{d.occupied}</span>
              <div className="fill" style={{ height: `${(d.occupied / peak) * 100}%` }} />
              <span className="muted small">{prettyDate(d.date).split(',')[0]}</span>
            </div>
          ))}
        </div>
      </div>

      {lastBill && (
        <div className="card" data-testid="last-bill">
          <h2>
            Bill issued · booking #{lastBill.id} · {lastBill.guest.full_name}
          </h2>
          <Bill booking={lastBill} />
        </div>
      )}

      <div className="columns">
        <div>
          <h2>Arrivals</h2>
          {data.arrivals.length === 0 && <p className="muted">No one else is arriving today.</p>}
          {data.arrivals.map((b) => (
            <BookingCard
              key={b.id}
              booking={b}
              showGuest
              busy={busy}
              actions={[
                {
                  label: 'Check in',
                  kind: 'primary',
                  testId: `check-in-${b.id}`,
                  onClick: () => act(() => api.checkIn(b.id), (x) => `Checked in ${x.guest.full_name} to room ${x.room.number}.`),
                },
              ]}
            />
          ))}
        </div>
        <div>
          <h2>In house</h2>
          {data.in_house.map((b) => (
            <BookingCard
              key={b.id}
              booking={b}
              items={items}
              showGuest
              busy={busy}
              onRoomService={(item, qty) =>
                act(() => api.roomService(b.id, item, qty), (x) => `Room service added to room ${x.room.number}.`)
              }
              actions={[
                {
                  label: 'Check out',
                  kind: 'primary',
                  testId: `check-out-${b.id}`,
                  onClick: () =>
                    act(() => api.checkOut(b.id), (x) => `Checked out room ${x.room.number}. Bill ${money(x.bill!.total)}.`),
                },
              ]}
            />
          ))}
        </div>
      </div>
    </section>
  )
}
