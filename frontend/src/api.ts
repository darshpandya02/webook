// Thin client for the WeBook REST API. JWT access and refresh tokens live in
// localStorage; a 401 triggers one refresh attempt before giving up.

export type Role = 'guest' | 'staff' | 'admin'

export interface User {
  id: number
  username: string
  email: string
  full_name: string
  role: Role
}

export interface RoomType {
  id: number
  name: string
  description: string
  beds: number
  capacity: number
  air_conditioned: boolean
  nightly_rate: string
}

export interface Quote {
  nights: number
  nightly_rate: string
  room_total: string
  service_total: string
  total: string
}

export interface AvailabilityRow {
  room_type: RoomType
  total_rooms: number
  available: number
  quote: Quote
}

export interface Item {
  id: number
  name: string
  category: string
  price: string
  is_available: boolean
}

export interface Order {
  id: number
  item: number
  item_name: string
  quantity: number
  unit_price: string
  line_total: string
  created_at: string
}

export type Status = 'confirmed' | 'checked_in' | 'checked_out' | 'cancelled'

export interface Booking {
  id: number
  status: Status
  check_in: string
  check_out: string
  nights: number
  guests_count: number
  nightly_rate: string
  room: { id: number; number: string; floor: number; room_type: number; room_type_name: string }
  guest: { id: number; username: string; full_name: string }
  room_service: Order[]
  charges: Quote
  bill: { id: number; nights: number; room_total: string; service_total: string; total: string; issued_at: string } | null
  created_at: string
}

export interface Occupancy {
  date: string
  rooms_total: number
  occupied: number
  occupancy_rate: number
  series: { date: string; occupied: number; rate: number }[]
  arrivals: Booking[]
  departures: Booking[]
  in_house: Booking[]
}

export interface AuditRow {
  id: number
  command: string
  actor: string | null
  booking: number | null
  outcome: 'ok' | 'rejected'
  detail: Record<string, unknown>
  created_at: string
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

const ACCESS = 'webook.access'
const REFRESH = 'webook.refresh'
const USER = 'webook.user'

export const session = {
  get user(): User | null {
    const raw = localStorage.getItem(USER)
    return raw ? (JSON.parse(raw) as User) : null
  },
  save(access: string, refresh: string, user: User) {
    localStorage.setItem(ACCESS, access)
    localStorage.setItem(REFRESH, refresh)
    localStorage.setItem(USER, JSON.stringify(user))
  },
  clear() {
    localStorage.removeItem(ACCESS)
    localStorage.removeItem(REFRESH)
    localStorage.removeItem(USER)
  },
}

function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === 'object') {
    const b = body as Record<string, unknown>
    if (typeof b.detail === 'string') return b.detail
    const first = Object.entries(b)[0]
    if (first) {
      const [field, value] = first
      const text = Array.isArray(value) ? value.join(' ') : String(value)
      return field === 'non_field_errors' ? text : `${field}: ${text}`
    }
  }
  return fallback
}

async function refreshAccess(): Promise<boolean> {
  const refresh = localStorage.getItem(REFRESH)
  if (!refresh) return false
  const r = await fetch('/api/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh }),
  })
  if (!r.ok) return false
  const data = await r.json()
  localStorage.setItem(ACCESS, data.access)
  return true
}

export async function request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const token = localStorage.getItem(ACCESS)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const r = await fetch(path, { ...init, headers })
  if (r.status === 401 && retry && token && (await refreshAccess())) {
    return request<T>(path, init, false)
  }
  const text = await r.text()
  const body = text ? JSON.parse(text) : null
  if (!r.ok) {
    if (r.status === 401 && token) {
      session.clear()
      window.dispatchEvent(new Event('webook:logout'))
    }
    throw new ApiError(r.status, errorMessage(body, `${r.status} ${r.statusText}`))
  }
  return body as T
}

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  login: (username: string, password: string) =>
    request<{ access: string; refresh: string; user: User }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  availability: (checkIn: string, checkOut: string, guests: number) =>
    request<{ results: AvailabilityRow[] }>(
      `/api/availability?check_in=${checkIn}&check_out=${checkOut}&guests=${guests}`,
    ),
  items: () => request<Item[]>('/api/items'),
  bookings: (params = '') => request<{ count: number; results: Booking[] }>(`/api/bookings${params}`),
  book: (body: { check_in: string; check_out: string; guests_count: number; room_type: number }) =>
    post<Booking>('/api/bookings', body),
  cancel: (id: number) => post<Booking>(`/api/bookings/${id}/cancel`),
  checkIn: (id: number) => post<Booking>(`/api/bookings/${id}/check-in`),
  checkOut: (id: number) => post<Booking>(`/api/bookings/${id}/check-out`),
  roomService: (id: number, item: number, quantity: number) =>
    post<Booking>(`/api/bookings/${id}/room-service`, { item, quantity }),
  occupancy: () => request<Occupancy>('/api/dashboard/occupancy'),
  audit: () => request<{ results: AuditRow[] }>('/api/audit-log?limit=100'),
}

export function money(v: string | number): string {
  return Number(v).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

export function isoDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function addDays(iso: string, n: number): string {
  const [y, m, d] = iso.split('-').map(Number)
  return isoDate(new Date(y, m - 1, d + n))
}

export function prettyDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
}

export const STATUS_LABEL: Record<Status, string> = {
  confirmed: 'Confirmed',
  checked_in: 'Checked in',
  checked_out: 'Checked out',
  cancelled: 'Cancelled',
}
