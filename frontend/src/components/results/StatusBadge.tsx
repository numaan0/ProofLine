import { AlertCircle, CheckCircle2, CircleDashed, XCircle } from 'lucide-react'
import { cn } from '../../lib/utils'

export const STATUS_CONFIG = {
  DONE: {
    icon: CheckCircle2,
    label: 'Supported',
    long: 'Evidence supports completion',
    className: 'bg-moss/10 text-moss-300 border-moss/30',
    iconClass: 'text-moss',
    stroke: '#526B59',
  },
  MISSING: {
    icon: XCircle,
    label: 'Not met',
    long: 'Visible evidence indicates this is not done',
    className: 'bg-brick/10 text-brick-300 border-brick/30',
    iconClass: 'text-brick',
    stroke: '#B95D4D',
  },
  CANT_TELL: {
    icon: AlertCircle,
    label: 'Needs evidence',
    long: 'Not enough visual evidence to verify',
    className: 'bg-amber/15 text-amber-400 border-amber/40',
    iconClass: 'text-amber-200',
    stroke: '#C08F38',
  },
  PENDING: {
    icon: CircleDashed,
    label: 'Not assessed',
    long: 'Not assessed',
    className: 'bg-ink/[0.05] text-ink-100 border-ink/15',
    iconClass: 'text-ink-50',
    stroke: '#6B7169',
  },
} as const

export type StatusKey = keyof typeof STATUS_CONFIG

export function statusConfig(status: string) {
  return STATUS_CONFIG[status as StatusKey] ?? STATUS_CONFIG.PENDING
}

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const cfg = statusConfig(status)
  const Icon = cfg.icon
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[12px] font-medium tracking-tight border shrink-0 whitespace-nowrap',
        cfg.className,
        className,
      )}
    >
      <Icon className={cn('w-3.5 h-3.5', cfg.iconClass)} aria-hidden />
      {cfg.label}
    </span>
  )
}
