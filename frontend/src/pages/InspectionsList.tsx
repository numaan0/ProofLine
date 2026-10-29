import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '../components/ui/Button'
import { ApiError, TERMINAL_STATUSES, api } from '../lib/api'
import { LIFECYCLE_COPY, OUTCOME_COPY, formatDateTime } from '../lib/format'
import { navigate } from '../lib/router'
import type { ApiErrorDetail, InspectionListItem } from '../lib/types'
import { cn } from '../lib/utils'

const REFRESH_MS = 4000

export default function InspectionsList() {
  const [items, setItems] = useState<InspectionListItem[] | null>(null)
  const [error, setError] = useState<ApiErrorDetail | null>(null)

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined
    const load = async () => {
      try {
        const data = await api.inspections()
        if (cancelled) return
        setItems(data.inspections)
        setError(null)
        // Keep refreshing only while something is still running.
        if (data.inspections.some((i) => !TERMINAL_STATUSES.has(i.status))) timer = window.setTimeout(load, REFRESH_MS)
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.details[0] : { code: 'UNKNOWN', message: 'Could not load inspections.' })
      }
    }
    load()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [])

  return (
    <main className="max-w-[1480px] mx-auto px-4 sm:px-6 lg:px-10 py-8 lg:py-12">
      <div className="flex flex-wrap items-end justify-between gap-4 mb-8">
        <div>
          <h1 className="font-display text-[34px] sm:text-[40px] leading-tight tracking-tight text-ink">Inspections</h1>
          <p className="mt-1.5 text-[14px] text-ink-100">Every inspection run on this machine, newest first.</p>
        </div>
        <Button onClick={() => navigate('/new')}>New inspection</Button>
      </div>

      {error && !items ? (
        <div role="alert" className="rounded-lg border border-brick/30 bg-brick/[0.06] px-4 py-3 text-[14px]">
          <p className="font-medium text-brick-300">{error.message}</p>
          {error.suggestion && <p className="text-ink-100 mt-0.5">{error.suggestion}</p>}
        </div>
      ) : !items ? (
        <p className="flex items-center gap-2 text-[14px] text-ink-100" role="status"><Loader2 className="w-4 h-4 animate-spin" aria-hidden />Loading…</p>
      ) : items.length === 0 ? (
        <div className="border-t border-rule pt-10 max-w-md">
          <p className="text-[15px] text-ink">No inspections yet.</p>
          <p className="mt-1 text-[14px] text-ink-100">Start with a work order and a few completion photos.</p>
        </div>
      ) : (
        <ul className="border-t border-rule">
          {items.map((item) => <Row key={item.inspection_id} item={item} />)}
        </ul>
      )}
    </main>
  )
}

function Row({ item }: { item: InspectionListItem }) {
  const running = !TERMINAL_STATUSES.has(item.status)
  const outcome = item.overall_outcome ? OUTCOME_COPY[item.overall_outcome] : null
  const tone = { moss: 'bg-moss', amber: 'bg-amber', brick: 'bg-brick' }
  const total = item.counts.done + item.counts.missing + item.counts.cant_tell
  return (
    <li className="border-b border-rule">
      <a
        href={`#/inspections/${item.inspection_id}`}
        className="grid grid-cols-12 gap-x-4 gap-y-1.5 items-center py-4 px-1 -mx-1 rounded-md hover:bg-paper/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-moss/40"
      >
        <div className="col-span-12 md:col-span-6 min-w-0">
          <p className="text-[15px] text-ink truncate">{item.title || 'Inspection'}</p>
          <p className="text-[12px] text-ink-50 mt-0.5">
            <span className="font-mono">{item.inspection_id}</span> · {formatDateTime(item.created_at)}
          </p>
        </div>
        <div className="col-span-7 md:col-span-3 flex items-center gap-2 text-[13px]">
          {running ? (
            <><Loader2 className="w-3.5 h-3.5 animate-spin text-ink-50" aria-hidden /><span className="text-ink-100">{LIFECYCLE_COPY[item.status]}</span></>
          ) : item.status === 'FAILED' ? (
            <><span className="w-2 h-2 rounded-full bg-brick" aria-hidden /><span className="text-brick-300">Failed (technical)</span></>
          ) : outcome ? (
            <><span className={cn('w-2 h-2 rounded-full', tone[outcome.tone])} aria-hidden /><span className="text-ink">{outcome.label}</span></>
          ) : null}
        </div>
        <div className="col-span-5 md:col-span-3 flex items-center justify-end gap-3 text-[12px] text-ink-100 tabular-nums">
          {total > 0 && !running && (
            <span title="Supported / not met / need evidence">
              <span className="text-moss-300">{item.counts.done}</span> · <span className="text-brick-300">{item.counts.missing}</span> · <span className="text-amber-400">{item.counts.cant_tell}</span>
            </span>
          )}
          {item.needs_action && item.status !== 'FAILED' && (
            <span className="px-1.5 py-0.5 rounded border border-amber/40 bg-amber/10 text-amber-400 whitespace-nowrap">Action needed</span>
          )}
        </div>
      </a>
    </li>
  )
}
