import { useRef, useState } from 'react'
import { Camera, Loader2, Upload } from 'lucide-react'
import { Button } from '../ui/Button'
import { ApiError, api, demoInspections, sampleFile } from '../../lib/api'
import type { ApiErrorDetail, InvestigationStep, Report, ReportTask } from '../../lib/types'
import { cn } from '../../lib/utils'
import { StatusBadge, statusConfig } from '../results/StatusBadge'

type Filter = 'all' | 'attention' | 'DONE' | 'MISSING'

const FILTERS: { key: Filter; label: string; test: (t: ReportTask) => boolean }[] = [
  { key: 'all', label: 'All', test: () => true },
  { key: 'attention', label: 'Needs attention', test: (t) => t.status === 'MISSING' || t.status === 'CANT_TELL' },
  { key: 'DONE', label: 'Supported', test: (t) => t.status === 'DONE' },
  { key: 'MISSING', label: 'Not met', test: (t) => t.status === 'MISSING' },
]

interface Props {
  report: Report
  selectedId: string | null
  onSelect: (task: ReportTask) => void
  onShowImage: (imageId: string) => void
  onRecheckStarted: () => void
}

export function TaskPanel({ report, selectedId, onSelect, onShowImage, onRecheckStarted }: Props) {
  const [filter, setFilter] = useState<Filter>('all')
  const active = FILTERS.find((f) => f.key === filter)!
  const tasks = report.tasks.filter(active.test)
  const photoNumber = new Map(report.images.map((img, i) => [img.id, i + 1]))

  return (
    <div>
      <div role="tablist" aria-label="Filter requirements" className="flex flex-wrap gap-1.5 mb-4">
        {FILTERS.map((f) => {
          const count = report.tasks.filter(f.test).length
          return (
            <button
              key={f.key}
              role="tab"
              type="button"
              aria-selected={filter === f.key}
              onClick={() => setFilter(f.key)}
              className={cn(
                'px-2.5 py-1 rounded-md text-[12px] border transition-colors',
                filter === f.key ? 'bg-ink text-white border-ink' : 'border-ink/12 text-ink-100 hover:text-ink hover:border-ink/25',
              )}
            >
              {f.label} <span className="tabular-nums opacity-70">{count}</span>
            </button>
          )
        })}
      </div>

      {tasks.length === 0 ? (
        <p className="text-[13px] text-ink-100 py-6">No requirements in this view.</p>
      ) : (
        <ol className="space-y-2">
          {tasks.map((task) => {
            const selected = task.id === selectedId
            const index = report.tasks.indexOf(task) + 1
            const cited = report.observations.filter((o) => task.observation_ids.includes(o.id))
            const related = report.observations.filter((o) => !task.observation_ids.includes(o.id) && o.task_ids.includes(task.id))
            return (
              <li
                key={task.id}
                className={cn(
                  'rounded-lg border bg-paper transition-colors',
                  selected ? 'border-ink/30 shadow-panel' : 'border-ink/10 hover:border-ink/20',
                )}
                style={selected ? { boxShadow: `inset 3px 0 0 ${statusConfig(task.status).stroke}` } : undefined}
              >
                <button
                  type="button"
                  onClick={() => onSelect(task)}
                  aria-expanded={selected}
                  className="w-full text-left px-4 py-3.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-moss/40 rounded-lg"
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-[14px] leading-snug text-ink">
                      <span className="font-mono text-[11px] text-ink-50 mr-2">{String(index).padStart(2, '0')}</span>
                      {task.description}
                    </p>
                    <StatusBadge status={task.status} />
                  </div>
                  {!selected && task.reasoning && (
                    <p className="mt-1.5 text-[13px] text-ink-100 leading-relaxed line-clamp-2">{task.reasoning}</p>
                  )}
                </button>

                {selected && (
                  <div className="px-4 pb-4 space-y-4">
                    <div>
                      <p className="text-[12px] text-ink-50 mb-1">{statusConfig(task.status).long}</p>
                      <p className="text-[13px] text-ink leading-relaxed">{task.reasoning}</p>
                    </div>

                    {task.observable_criteria && task.observable_criteria !== task.description && (
                      <div>
                        <p className="text-[12px] text-ink-50 mb-1">What a photo needs to show</p>
                        <p className="text-[13px] text-ink-100 leading-relaxed">{task.observable_criteria}</p>
                      </div>
                    )}

                    {cited.length > 0 && (
                      <ObservationList title="Evidence cited" observations={cited} photoNumber={photoNumber} onShowImage={onShowImage} />
                    )}
                    {related.length > 0 && (
                      <ObservationList title="Other observations about this requirement" observations={related} photoNumber={photoNumber} onShowImage={onShowImage} muted />
                    )}
                    {cited.length === 0 && related.length === 0 && (
                      <p className="text-[13px] text-ink-100">None of the submitted photos showed anything about this requirement.</p>
                    )}

                    {task.investigation.length > 0 && <InvestigationSteps steps={task.investigation} />}

                    {task.follow_up?.needed && (
                      <FollowUpCard
                        inspectionId={report.inspection_id}
                        task={task}
                        busy={report.status === 'REVERIFYING'}
                        onStarted={onRecheckStarted}
                      />
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}

function FollowUpCard({ inspectionId, task, busy, onStarted }: {
  inspectionId: string
  task: ReportTask
  busy: boolean
  onStarted: () => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [errors, setErrors] = useState<ApiErrorDetail[]>([])
  const followUp = task.follow_up!
  const checking = followUp.status === 'CHECKING'

  const upload = async (files: File[]) => {
    if (!files.length) return
    setUploading(true)
    setErrors([])
    try {
      await api.addFollowUpPhotos(inspectionId, task.id, files)
      onStarted()
    } catch (err) {
      setErrors(err instanceof ApiError ? err.details : [{ code: 'UNKNOWN', message: 'Could not upload the photo.' }])
    } finally {
      setUploading(false)
      if (input.current) input.current.value = ''
    }
  }

  return (
    <div className="rounded-lg border border-amber/40 bg-amber/[0.08] px-3.5 py-3">
      <p className="flex items-center gap-2 text-[13px] font-medium text-ink">
        <Camera className="w-4 h-4 text-amber-400" aria-hidden />
        {checking ? 'Checking the new photo' : 'One more photo is needed'}
      </p>
      <p className="mt-1 text-[13px] text-ink-100 leading-relaxed">{followUp.request}</p>

      {checking ? (
        <p className="mt-2.5 flex items-center gap-2 text-[12px] text-ink-100" role="status">
          <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden />
          Re-checking this requirement with the new photo. Other results stay as they are.
        </p>
      ) : (
        <div className="mt-2.5">
          <input
            ref={input}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            multiple
            className="sr-only"
            id={`follow-up-${task.id}`}
            onChange={(e) => upload(Array.from(e.target.files ?? []))}
          />
          <Button size="sm" variant="secondary" disabled={uploading || busy} onClick={() => input.current?.click()}>
            {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden /> : <Upload className="w-3.5 h-3.5" aria-hidden />}
            {uploading ? 'Uploading…' : 'Add follow-up photo'}
          </Button>
          {demoInspections.has(inspectionId) && (
            <button
              type="button"
              disabled={uploading || busy}
              onClick={async () => {
                try {
                  const sample = (await api.samples()).photos.find((p) => p.role === 'follow_up')!
                  await upload([await sampleFile(sample.url, sample.name)])
                } catch (err) {
                  setErrors(err instanceof ApiError ? err.details : [{ code: 'UNKNOWN', message: 'Could not load the sample photo.' }])
                }
              }}
              className="ml-3 text-[12px] text-moss-300 hover:underline disabled:opacity-40"
            >
              Use the sample follow-up photo
            </button>
          )}
          {busy && !uploading && <p className="mt-1.5 text-[12px] text-ink-50">Wait for the current photo check to finish.</p>}
          {followUp.image_ids.length > 0 && !followUp.last_error && (
            <p className="mt-1.5 text-[12px] text-ink-50">
              {followUp.image_ids.length} follow-up photo{followUp.image_ids.length === 1 ? '' : 's'} checked so far; still not enough to decide.
            </p>
          )}
        </div>
      )}

      {followUp.last_error && !checking && (
        <p className="mt-2 text-[12px] text-brick-300" role="alert">{followUp.last_error}</p>
      )}
      {errors.length > 0 && (
        <ul className="mt-2 space-y-1 text-[12px]" role="alert">
          {errors.map((e, i) => (
            <li key={i}>
              <span className="text-brick-300">{e.message}</span>
              {e.suggestion && <span className="text-ink-100"> {e.suggestion}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function describeStep(step: InvestigationStep): string {
  const photo = typeof step.args.photo === 'string' ? `photo ${step.args.photo.replace('P', '')}` : 'a photo'
  switch (step.tool) {
    case 'look_closer':
      return `Looked closer at ${photo}: “${String(step.args.question ?? '')}”`
    case 'count_objects':
      return `Counted “${String(step.args.object_phrase ?? '')}” in ${photo} with SAM 3.1`
    case 'finalize':
      return 'Recorded a decision'
    case 'follow_up_check': {
      const n = Number(step.args.photos ?? 1)
      return `Re-checked this requirement with ${n} follow-up photo${n === 1 ? '' : 's'}`
    }
    case 'compare_before_after': {
      const pairs = Array.isArray(step.args.pairs) ? (step.args.pairs as string[]) : []
      return `Compared ${pairs.map((p) => { const [b, a] = p.split('->'); return `before photo ${b} with photo ${a}` }).join(', ') || 'before and after photos'}`
    }
    case 'investigation':
      return 'Investigation stopped'
    default:
      return `Rejected tool call (${step.tool})`
  }
}

function stepResult(step: InvestigationStep): string {
  if (step.tool !== 'finalize' && step.tool !== 'follow_up_check') return step.result
  // "CANT_TELL (downgraded: ...)" -> "Needs evidence (downgraded: ...)"
  const [status, ...rest] = step.result.split(' ')
  return [statusConfig(status).label, ...rest].join(' ')
}

function InvestigationSteps({ steps }: { steps: InvestigationStep[] }) {
  return (
    <div>
      <p className="text-[12px] text-ink-50 mb-1.5">How ProofLine checked this</p>
      <ol className="space-y-1.5 border-l border-rule ml-1">
        {steps.map((s, i) => {
          const firstFollowUp = s.round === 'follow_up' && steps[i - 1]?.round !== 'follow_up'
          return (
            <li key={i} className="pl-3 relative text-[12px] leading-relaxed">
              {firstFollowUp && <p className="text-[11px] uppercase tracking-wide text-ink-50 mb-1">After the follow-up photo</p>}
              <span aria-hidden className={cn('absolute -left-[4px] w-[7px] h-[7px] rounded-full', s.ok ? 'bg-ink-50' : 'bg-brick',
                firstFollowUp ? 'top-[27px]' : 'top-[7px]')} />
              <p className="text-ink">{describeStep(s)}</p>
              <p className={s.ok ? 'text-ink-100' : 'text-brick-300'}>{stepResult(s)}</p>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function ObservationList({ title, observations, photoNumber, onShowImage, muted }: {
  title: string
  observations: Report['observations']
  photoNumber: Map<string, number>
  onShowImage: (id: string) => void
  muted?: boolean
}) {
  return (
    <div>
      <p className="text-[12px] text-ink-50 mb-1.5">{title}</p>
      <ul className="space-y-2">
        {observations.map((o) => (
          <li key={o.id} className="text-[13px] leading-relaxed">
            <p className={muted ? 'text-ink-100' : 'text-ink'}>
              {o.image_id && (
                <button
                  type="button"
                  onClick={() => onShowImage(o.image_id!)}
                  className="font-mono text-[11px] mr-1.5 px-1.5 py-0.5 rounded bg-ink/[0.06] text-ink-100 hover:bg-ink/10 hover:text-ink align-[1px]"
                  aria-label={`Show photo ${photoNumber.get(o.image_id)}`}
                >
                  PHOTO {photoNumber.get(o.image_id)}
                </button>
              )}
              {o.text}
            </p>
            {o.limitations && <p className="text-[12px] text-ink-50 mt-0.5">Limit: {o.limitations}</p>}
          </li>
        ))}
      </ul>
    </div>
  )
}
