import { useState } from 'react'
import { money, prettyDate, STATUS_LABEL, type Booking, type Item } from '../api'

interface Props {
  booking: Booking
  items?: Item[]
  showGuest?: boolean
  actions?: { label: string; kind?: 'primary' | 'secondary' | 'danger'; onClick: () => void; testId?: string }[]
  onRoomService?: (itemId: number, quantity: number) => void
  busy?: boolean
}

export function Bill({ booking }: { booking: Booking }) {
  const c = booking.bill ?? booking.charges
  return (
    <table className="bill" data-testid={`bill-${booking.id}`}>
      <tbody>
        <tr>
          <td>
            Room {booking.room.number}, {booking.nights} night(s) x {money(booking.nightly_rate)}
          </td>
          <td className="num">{money(c.room_total)}</td>
        </tr>
        {booking.room_service.map((o) => (
          <tr key={o.id} className="muted">
            <td>
              {o.quantity} x {o.item_name} @ {money(o.unit_price)}
            </td>
            <td className="num">{money(o.line_total)}</td>
          </tr>
        ))}
        <tr>
          <td>Room service</td>
          <td className="num">{money(c.service_total)}</td>
        </tr>
        <tr className="total">
          <td>{booking.bill ? 'Total billed' : 'Running total'}</td>
          <td className="num" data-testid="bill-total">
            {money(c.total)}
          </td>
        </tr>
      </tbody>
    </table>
  )
}

export default function BookingCard({ booking, items, showGuest, actions = [], onRoomService, busy }: Props) {
  const [showBill, setShowBill] = useState(booking.status === 'checked_out')
  const [item, setItem] = useState<number>(items?.[0]?.id ?? 0)
  const [qty, setQty] = useState(1)
  return (
    <article className="card booking" data-testid={`booking-${booking.id}`} data-status={booking.status}>
      <div className="row">
        <div>
          <h3>
            Room {booking.room.number} <span className="muted small">{booking.room.room_type_name}</span>
          </h3>
          <p className="small">
            #{booking.id} · {prettyDate(booking.check_in)} to {prettyDate(booking.check_out)} · {booking.nights} night(s) ·{' '}
            {booking.guests_count} guest(s)
            {showGuest && (
              <>
                {' '}
                · <strong>{booking.guest.full_name}</strong>
              </>
            )}
          </p>
        </div>
        <span className={`status ${booking.status}`}>{STATUS_LABEL[booking.status]}</span>
      </div>
      <div className="row">
        <span className="big">{money((booking.bill ?? booking.charges).total)}</span>
        <div className="actions">
          <button className="link" onClick={() => setShowBill((v) => !v)}>
            {showBill ? 'Hide bill' : 'Bill'}
          </button>
          {actions.map((a) => (
            <button key={a.label} className={a.kind ?? 'secondary'} disabled={busy} onClick={a.onClick} data-testid={a.testId}>
              {a.label}
            </button>
          ))}
        </div>
      </div>
      {onRoomService && items && items.length > 0 && booking.status === 'checked_in' && (
        <div className="roomservice">
          <select aria-label="Room service item" value={item} onChange={(e) => setItem(Number(e.target.value))}>
            {items.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name} ({money(i.price)})
              </option>
            ))}
          </select>
          <input aria-label="Quantity" type="number" min={1} max={20} value={qty} onChange={(e) => setQty(Number(e.target.value))} />
          <button className="secondary" disabled={busy} onClick={() => onRoomService(item, qty)} data-testid={`add-service-${booking.id}`}>
            Add room service
          </button>
        </div>
      )}
      {showBill && <Bill booking={booking} />}
    </article>
  )
}
