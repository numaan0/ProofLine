import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, Loader2 } from 'lucide-react'
import { EvidenceViewer } from '../components/report/EvidenceViewer'
import { StageProgress } from '../components/report/StageProgress'
import { TaskPanel } from '../components/report/TaskPanel'
import { Button } from '../components/ui/Button'
import { ApiError, TERMINAL_STATUSES, api } from '../lib/api'
import { OUTCOME_COPY, formatDateTime } from '../lib/format'
import { navigate } from '../lib/router'
import type { ApiErrorDetail, InspectionStatus, Report, ReportTask } from '../lib/types'
import { cn } from '../lib/utils'

const POLL_MS = 1500
const SLOW_STAGE_MS = 25000

export default function InspectionView({ id, taskId }: { id: string; taskId?: string }) {
  const [status, setStatus] = useState<InspectionStatus | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState<ApiErrorDetail | null>(null)
  const [slow, setSlow] = useState(false)
  const [pollKey, setPollKey] = useState(0)
  const stageSince = useRef<{ stage: string; at: number }>({ stage: '', at: Date.now() })

  const poll = useCallback(async () => {
    try {
      const s = await api.inspection(id)
      setStatus(s)
      setError(null)
      if (s.status !== stageSince.current.stage) stageSince.current = { stage: s.status, at: Date.now() }
      setSlow(Date.now() - stageSince.current.at > SLOW_STAGE_MS)
      // A follow-up re-check runs on an existing report, so keep showing (and refreshing) it.
      const terminal = TERMINAL_STATUSES.has(s.status)
      if (terminal || s.status === 'REVERIFYING') {
        setReport(await api.report(id))
        return terminal
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.details[0] : { code: 'UNKNOWN', message: 'Could not load this inspection.' })
      if (err instanceof ApiError && err.status === 404) return true
    }
    return false
  }, [id])

  useEffect(() => {
    setStatus(null)
    setReport(null)
  }, [id])

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined
    const tick = async () => {
      const done = await poll()
      if (!cancelled && !done) timer = window.setTimeout(tick, POLL_MS)
    }
    tick()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [poll, pollKey])

  if (error && !status) {
    return (
      <CenteredMessage title={error.code === 'NOT_FOUND' || error.code === 'HTTP_404' ? 'Inspection not found' : 'Could not load this inspection'} body={error.suggestion ?? error.message}>
        <Button variant="secondary" onClick={() => navigate('/inspections')}>Back to inspections</Button>
      </CenteredMessage>
    )
  }
  if (!status) {
    return (
      <div className="flex items-center justify-center py-32 text-ink-100 text-[14px] gap-2" role="status">
        <Loader2 className="w-4 h-4 animate-spin" aria-hidden /> Loading inspection…
      </div>
    )
  }
  if (status.status === 'FAILED') {
    return (
      <FailedView
        status={status}
        onRetry={async () => {
          await api.retry(id)
          setReport(null)
          setStatus(null)
          setPollKey((k) => k + 1)
        }}
      />
    )
  }
  if (!report) return <StageProgress status={status} slow={slow} />
  return <ReportWorkspace report={report} initialTaskId={taskId} connectionError={error} onRecheckStarted={() => setPollKey((k) => k + 1)} />
}

function ReportWorkspace({ report, initialTaskId, connectionError, onRecheckStarted }: {
  report: Report
  initialTaskId?: string
  connectionError: ApiErrorDetail | null
  onRecheckStarted: () => void
}) {
  const firstAttention = report.tasks.find((t) => t.status === 'MISSING' || t.status === 'CANT_TELL')
  const initialTask = report.tasks.find((t) => t.id === initialTaskId) ?? firstAttention ?? report.tasks[0] ?? null
  // Track the id, not the object: the report is replaced when a follow-up re-check finishes.
  const [selectedId, setSelectedId] = useState<string | null>(initialTask?.id ?? null)
  const selected = report.tasks.find((t) => t.id === selectedId) ?? null
  const [imageId, setImageId] = useState<string | null>(initialTask?.evidence[0]?.image_id ?? report.images[0]?.id ?? null)

  // When a re-check replaces the report, follow the selected requirement's evidence to the photo it now cites.
  useEffect(() => {
    if (selected?.evidence.length && !selected.evidence.some((e) => e.image_id === imageId)) setImageId(selected.evidence[0].image_id)
  }, [report]) // eslint-disable-line react-hooks/exhaustive-deps

  const selectTask = (task: ReportTask) => {
    setSelectedId((cur) => (cur === task.id ? null : task.id))
    if (task.evidence[0]) setImageId(task.evidence[0].image_id)
  }

  const outcome = report.overall_outcome ? OUTCOME_COPY[report.overall_outcome] : null
  const toneClass = { moss: 'text-moss-300 bg-moss/10 border-moss/30', amber: 'text-amber-400 bg-amber/15 border-amber/40', brick: 'text-brick-300 bg-brick/10 border-brick/30' }

  return (
    <main className="max-w-[1480px] mx-auto px-4 sm:px-6 lg:px-10 py-6 lg:py-8">
      <header className="mb-6 lg:mb-7">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-ink-50">
          <span className="font-mono">{report.inspection_id}</span>
          <span aria-hidden>·</span>
          <time dateTime={report.created_at}>{formatDateTime(report.created_at)}</time>
          <span aria-hidden>·</span>
          <span>{report.images.length} photo{report.images.length === 1 ? '' : 's'}</span>
        </div>
        <div className="mt-2 flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
          <div className="min-w-0">
            <h1 className="font-display text-[28px] sm:text-[34px] leading-tight tracking-tight text-ink">{report.title || 'Inspection'}</h1>
            {report.summary && <p className="mt-1.5 text-[14px] text-ink-100 max-w-3xl">{report.summary}</p>}
          </div>
          <div className="flex flex-wrap items-center gap-2 shrink-0">
            {outcome && <span className={cn('px-2.5 py-1 rounded-md border text-[13px] font-medium', toneClass[outcome.tone])}>{outcome.label}</span>}
            <Count label="Supported" value={report.counts.done} />
            <Count label="Not met" value={report.counts.missing} />
            <Count label="Need evidence" value={report.counts.cant_tell} />
          </div>
        </div>
        {report.status === 'REVERIFYING' && (
          <p className="mt-3 flex items-center gap-2 text-[13px] text-ink-100" role="status">
            <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden /> Checking the follow-up photo. Results below update when it finishes.
          </p>
        )}
        {connectionError && (
          <p className="mt-3 text-[12px] text-brick-300" role="status">Connection problem: {connectionError.message}</p>
        )}
      </header>

      <div className="grid grid-cols-12 gap-6 lg:gap-8 items-start">
        <section className="col-span-12 lg:col-span-7 xl:col-span-8 min-w-0 lg:sticky lg:top-20" aria-label="Photo evidence">
          <EvidenceViewer images={report.images} observations={report.observations} activeImageId={imageId} onSelectImage={setImageId} task={selected} />
        </section>
        <section className="col-span-12 lg:col-span-5 xl:col-span-4 min-w-0" aria-label="Requirements">
          <TaskPanel report={report} selectedId={selectedId} onSelect={selectTask} onShowImage={setImageId} onRecheckStarted={onRecheckStarted} />
          <details className="mt-6 text-[13px]">
            <summary className="cursor-pointer text-ink-100 hover:text-ink">Original work order</summary>
            <pre className="mt-2 whitespace-pre-wrap font-sans text-ink-100 leading-relaxed bg-paper border border-ink/10 rounded-lg px-3.5 py-3">{report.work_order_text}</pre>
          </details>
          <p className="mt-4 text-[12px] text-ink-50 leading-relaxed">
            Findings describe what the submitted photos show. They are not a certification of safety, code compliance or hidden work.
          </p>
        </section>
      </div>
    </main>
  )
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <span className="px-2.5 py-1 rounded-md border border-ink/10 bg-paper text-[13px] text-ink-100">
      <span className="font-medium text-ink tabular-nums">{value}</span> {label}
    </span>
  )
}

function FailedView({ status, onRetry }: { status: InspectionStatus; onRetry: () => Promise<void> }) {
  const [retrying, setRetrying] = useState(false)
  const [retryError, setRetryError] = useState<string | null>(null)
  const retry = async () => {
    setRetrying(true)
    setRetryError(null)
    try {
      await onRetry()
    } catch (err) {
      setRetryError(err instanceof ApiError ? err.message : 'Could not restart the inspection.')
      setRetrying(false)
    }
  }
  return (
    <CenteredMessage
      icon
      title="This inspection couldn't finish"
      body={`${status.error?.message ?? 'A technical problem stopped the inspection.'} No findings were recorded, so nothing here should be read as a result about the work.`}
      code={status.error?.code}
    >
      <Button onClick={retry} disabled={retrying}>
        {retrying ? <><Loader2 className="w-4 h-4 animate-spin" aria-hidden />Restarting…</> : 'Retry with the same photos'}
      </Button>
      <Button variant="secondary" onClick={() => navigate('/new')}>Start a new inspection</Button>
      {retryError && <p className="w-full text-[13px] text-brick-300" role="alert">{retryError}</p>}
    </CenteredMessage>
  )
}

function CenteredMessage({ title, body, code, icon, children }: { title: string; body: string; code?: string; icon?: boolean; children?: React.ReactNode }) {
  return (
    <main className="max-w-xl mx-auto px-4 py-20 sm:py-28">
      {icon && <AlertTriangle className="w-6 h-6 text-brick mb-4" aria-hidden />}
      <h1 className="font-display text-[28px] leading-tight tracking-tight text-ink">{title}</h1>
      <p className="mt-3 text-[15px] text-ink-100 leading-relaxed">{body}</p>
      {code && <p className="mt-2 font-mono text-[12px] text-ink-50">Error code: {code}</p>}
      <div className="mt-6 flex flex-wrap gap-2">{children}</div>
    </main>
  )
}
