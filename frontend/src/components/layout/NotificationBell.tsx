import { useCallback, useEffect, useRef, useState } from 'react'
import { Bell } from 'lucide-react'
import { api } from '../../lib/api'
import { relativeTime } from '../../lib/format'
import { navigate } from '../../lib/router'
import type { AppNotification } from '../../lib/types'
import { cn } from '../../lib/utils'

const POLL_MS = 5000

const TONE: Record<string, string> = {
  INSPECTION_COMPLETED: 'bg-moss',
  INSPECTION_ATTENTION: 'bg-brick',
  FOLLOW_UP_REQUESTED: 'bg-amber',
  INSPECTION_FAILED: 'bg-brick',
  FOLLOW_UP_CHECKED: 'bg-moss',
  FOLLOW_UP_FAILED: 'bg-brick',
}

export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<AppNotification[]>([])
  const [unread, setUnread] = useState(0)
  const [failed, setFailed] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)

  const load = useCallback(async () => {
    try {
      const data = await api.notifications()
      setItems(data.notifications)
      setUnread(data.unread_count)
      setFailed(false)
    } catch {
      setFailed(true)
    }
  }, [])

  useEffect(() => {
    load()
    const t = window.setInterval(load, POLL_MS)
    return () => window.clearInterval(t)
  }, [load])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        buttonRef.current?.focus()
      }
    }
    const onClick = (e: MouseEvent) => {
      if (!panelRef.current?.contains(e.target as Node) && !buttonRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [open])

  const openItem = async (n: AppNotification) => {
    setOpen(false)
    if (!n.read) {
      setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, read: true } : x)))
      setUnread((u) => Math.max(0, u - 1))
      api.markRead(n.id).catch(load)
    }
    if (n.inspection_id) navigate(`/inspections/${n.inspection_id}`)
  }

  const markAll = async () => {
    setItems((prev) => prev.map((x) => ({ ...x, read: true })))
    setUnread(0)
    api.markAllRead().catch(load)
  }

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}
        className="relative w-9 h-9 rounded-md flex items-center justify-center text-ink-100 hover:text-ink hover:bg-ink/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-moss/40"
      >
        <Bell className="w-[18px] h-[18px]" strokeWidth={1.75} />
        {unread > 0 && (
          <span className="absolute top-1 right-1 min-w-[16px] h-4 px-1 rounded-full bg-brick text-white text-[10px] font-semibold leading-4 text-center tabular-nums">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div
          ref={panelRef}
          role="dialog"
          aria-label="Notifications"
          className="absolute right-0 mt-2 w-[min(380px,calc(100vw-2rem))] rounded-xl border border-ink/10 bg-paper shadow-panel-strong overflow-hidden"
        >
          <div className="flex items-center justify-between px-4 py-3 border-b border-ink/8">
            <p className="text-[13px] font-medium text-ink">Notifications</p>
            {unread > 0 && (
              <button type="button" onClick={markAll} className="text-[12px] text-moss-300 hover:underline">
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-[420px] overflow-auto">
            {failed && items.length === 0 ? (
              <p className="px-4 py-6 text-[13px] text-ink-100">Notifications are unavailable while the server is unreachable.</p>
            ) : items.length === 0 ? (
              <p className="px-4 py-6 text-[13px] text-ink-100">Nothing yet. You will be notified when an inspection finishes or needs a photo.</p>
            ) : (
              <ul>
                {items.map((n) => (
                  <li key={n.id}>
                    <button
                      type="button"
                      onClick={() => openItem(n)}
                      className={cn(
                        'w-full text-left px-4 py-3 flex gap-3 border-b border-ink/[0.06] last:border-0 hover:bg-chalk/70 focus-visible:outline-none focus-visible:bg-chalk',
                        !n.read && 'bg-amber/[0.05]',
                      )}
                    >
                      <span className={cn('mt-1.5 w-2 h-2 rounded-full shrink-0', TONE[n.type] ?? 'bg-ink-50', n.read && 'opacity-30')} />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-baseline justify-between gap-2">
                          <span className={cn('text-[13px] text-ink truncate', !n.read && 'font-medium')}>{n.title}</span>
                          <span className="text-[11px] text-ink-50 shrink-0">{relativeTime(n.created_at)}</span>
                        </span>
                        <span className="block text-[12px] text-ink-100 leading-snug mt-0.5">{n.message}</span>
                        {n.inspection_title && (
                          <span className="block text-[11px] text-ink-50 mt-1 truncate">{n.inspection_title}</span>
                        )}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
