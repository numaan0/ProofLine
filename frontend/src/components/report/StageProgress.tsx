import { Check, Loader2 } from 'lucide-react'
import type { InspectionStatus } from '../../lib/types'
import { cn } from '../../lib/utils'

// Order matches the backend orchestrator. Submission checks run before the inspection exists.
const STAGES = [
  { key: 'QUEUED', label: 'Submission checked', detail: 'Work order and every photo passed validation.' },
  { key: 'PLANNING', label: 'Planning requirements', detail: 'Turning the work order into checkable requirements.' },
  { key: 'ANALYZING', label: 'Analyzing photographs', detail: 'Recording what each photo actually shows.' },
  { key: 'COMPARING', label: 'Comparing before and after', detail: 'Only when before photos were added: checks it is the same place and what changed.' },
  { key: 'VERIFYING', label: 'Verifying requirements', detail: 'Matching observations to each requirement.' },
  { key: 'INVESTIGATING', label: 'Investigating open questions', detail: 'Takes a closer look or counts objects when a requirement is unresolved.' },
  { key: 'GROUNDING', label: 'Locating cited objects', detail: 'Runs SAM 3.1 only when a finding cites a specific object.' },
] as const

const ORDER: Record<string, number> = { QUEUED: 0, PLANNING: 1, ANALYZING: 2, COMPARING: 3, VERIFYING: 4, INVESTIGATING: 5, GROUNDING: 6 }

export function StageProgress({ status, slow }: { status: InspectionStatus; slow: boolean }) {
  const current = ORDER[status.status] ?? 0
  return (
    <main className="max-w-[1480px] mx-auto px-4 sm:px-6 lg:px-10 py-10 lg:py-16">
      <div className="max-w-2xl">
        <p className="font-mono text-[12px] text-ink-50">Inspection {status.inspection_id}</p>
        <h1 className="mt-2 font-display text-[30px] sm:text-[36px] leading-tight tracking-tight text-ink">{status.title || 'Inspection'}</h1>
        <p className="mt-2 text-[14px] text-ink-100">
          {status.images_count} photo{status.images_count === 1 ? '' : 's'} submitted. This page updates as each stage finishes.
        </p>

        <ol className="mt-10 border-l border-rule ml-[11px]" aria-live="polite">
          {STAGES.map((stage, i) => {
            const state = i < current ? 'done' : i === current ? 'active' : 'upcoming'
            // Stage 0 is complete as soon as the inspection exists; QUEUED means waiting for PLANNING to start.
            const effective = i === 0 ? 'done' : state
            return (
              <li key={stage.key} className="relative pl-8 pb-8 last:pb-0">
                <span
                  className={cn(
                    'absolute -left-[12px] top-0 w-6 h-6 rounded-full flex items-center justify-center border',
                    effective === 'done' && 'bg-moss border-moss text-white',
                    effective === 'active' && 'bg-paper border-ink text-ink',
                    effective === 'upcoming' && 'bg-chalk border-rule text-ink-50',
                  )}
                  aria-hidden
                >
                  {effective === 'done' ? <Check className="w-3.5 h-3.5" strokeWidth={2.5} />
                    : effective === 'active' ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      : <span className="w-1.5 h-1.5 rounded-full bg-current" />}
                </span>
                <p className={cn('text-[15px] leading-6', effective === 'upcoming' ? 'text-ink-50' : 'text-ink', effective === 'active' && 'font-medium')}>
                  {stage.label}
                  <span className="sr-only">{effective === 'done' ? ' (done)' : effective === 'active' ? ' (in progress)' : ''}</span>
                </p>
                <p className={cn('text-[13px] mt-0.5', effective === 'upcoming' ? 'text-ink-50/80' : 'text-ink-100')}>{stage.detail}</p>
                {effective === 'active' && slow && (
                  <p className="text-[12px] text-ink-50 mt-1.5">Still waiting on the AI model. Large or numerous photos take longer.</p>
                )}
              </li>
            )
          })}
        </ol>
      </div>
    </main>
  )
}
