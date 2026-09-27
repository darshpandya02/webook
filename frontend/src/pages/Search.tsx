import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { addDays, api, isoDate, money, prettyDate, type AvailabilityRow, type Booking } from '../api'
import { useAuth } from '../auth'

export default function Search() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const today = isoDate(new Date())
  const [checkIn, setCheckIn] = useState(today)
  const [checkOut, setCheckOut] = useState(addDays(today, 2))
  const [guests, setGuests] = useState(2)
  const [rows, setRows] = useState<AvailabilityRow[] | null>(null)
  const [searched, setSearched] = useState({ checkIn, checkOut, guests })
  const [error, setError] = useState('')
  const [booked, setBooked] = useState<Booking | null>(null)
  const [busy, setBusy] = useState<number | 'search' | null>(null)

  async function search(e?: FormEvent) {
    e?.preventDefault()
    setBusy('search')
    setError('')
    setBooked(null)
    try {
      const r = await api.availability(checkIn, checkOut, guests)
      setRows(r.results)
      setSearched({ checkIn, checkOut, guests })
    } catch (err) {
      setRows(null)
      setError(err instanceof Error ? err.message : 'Search failed')
    } finally {
      setBusy(null)
    }
  }

  useEffect(() => {
    void search()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function book(row: AvailabilityRow) {
    if (!user) {
      navigate('/login', { state: { from: '/' } })
      return
    }
    setBusy(row.room_type.id)
    setError('')
    try {
      const b = await api.book({
        check_in: searched.checkIn,
        check_out: searched.checkOut,
        guests_count: searched.guests,
        room_type: row.room_type.id,
      })
      setBooked(b)
      const r = await api.availability(searched.checkIn, searched.checkOut, searched.guests)
      setRows(r.results)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Booking failed')
    } finally {
      setBusy(null)
    }
  }

  return (
    <section>
      <div className="hero">
        <h1>Find a room</h1>
        <p className="muted">Live availability from Postgres. Prices are the nightly rate times nights; room service is added at check-out.</p>
        <form className="searchbar" onSubmit={search}>
          <label>
            Check-in
            <input type="date" name="check_in" value={checkIn} min={today} onChange={(e) => setCheckIn(e.target.value)} required />
          </label>
          <label>
            Check-out
            <input type="date" name="check_out" value={checkOut} min={addDays(checkIn, 1)} onChange={(e) => setCheckOut(e.target.value)} required />
          </label>
          <label>
            Guests
            <select name="guests" value={guests} onChange={(e) => setGuests(Number(e.target.value))}>
              {[1, 2, 3, 4].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <button className="primary" disabled={busy === 'search'}>
            {busy === 'search' ? 'Searching...' : 'Search'}
          </button>
        </form>
      </div>

      {error && <p className="error banner" role="alert">{error}</p>}
      {booked && (
        <div className="success banner" role="status" data-testid="booking-confirmed">
          Booked: room <strong>{booked.room.number}</strong> ({booked.room.room_type_name}), {prettyDate(booked.check_in)} to{' '}
          {prettyDate(booked.check_out)}, {money(booked.charges.total)}. Booking #{booked.id}. <Link to="/bookings">View bookings</Link>
        </div>
      )}

      {rows && (
        <>
          <p className="muted">
            {prettyDate(searched.checkIn)} to {prettyDate(searched.checkOut)} · {rows[0]?.quote.nights ?? 0} night(s) · {searched.guests} guest(s)
          </p>
          <div className="grid">
            {rows.map((row) => (
              <article key={row.room_type.id} className="card room" data-testid="room-type">
                <h3>{row.room_type.name}</h3>
                <p className="muted">{row.room_type.description}</p>
                <p className="small">
                  Sleeps {row.room_type.capacity} · {row.room_type.beds} bed(s)
                  {row.room_type.air_conditioned ? ' · AC' : ''}
                </p>
                <div className="price">
                  <span className="big">{money(row.quote.total)}</span>
                  <span className="muted small">
                    {money(row.room_type.nightly_rate)} x {row.quote.nights}
                  </span>
                </div>
                <div className="row">
                  <span className={row.available ? 'avail' : 'soldout'}>
                    {row.available ? `${row.available} of ${row.total_rooms} free` : 'Sold out'}
                  </span>
                  <button className="primary" disabled={!row.available || busy !== null} onClick={() => book(row)}>
                    {busy === row.room_type.id ? 'Booking...' : user ? 'Book' : 'Sign in to book'}
                  </button>
                </div>
              </article>
            ))}
          </div>
          {rows.length === 0 && <p>No room types sleep {searched.guests} guests.</p>}
        </>
      )}
    </section>
  )
}
