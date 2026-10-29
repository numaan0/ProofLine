import type { LifecycleStatus, OverallOutcome } from './types'

export function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export function relativeTime(iso: string) {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  return formatDateTime(iso)
}

export function shortId(id: string) {
  return id.replace(/^ins_/, '').slice(0, 8).toUpperCase()
}

export const OUTCOME_COPY: Record<Exclude<OverallOutcome, null>, { label: string; tone: 'moss' | 'amber' | 'brick' }> = {
  NO_FLAGGED_ISSUES: { label: 'No flagged issues', tone: 'moss' },
  EVIDENCE_INCOMPLETE: { label: 'Evidence incomplete', tone: 'amber' },
  ATTENTION_REQUIRED: { label: 'Attention required', tone: 'brick' },
}

export const LIFECYCLE_COPY: Record<LifecycleStatus, string> = {
  QUEUED: 'Queued',
  PLANNING: 'Planning',
  ANALYZING: 'Analyzing photos',
  COMPARING: 'Comparing before and after',
  VERIFYING: 'Verifying',
  INVESTIGATING: 'Investigating',
  GROUNDING: 'Locating objects',
  REVERIFYING: 'Checking follow-up photo',
  NEEDS_USER_ACTION: 'Needs your input',
  COMPLETED: 'Complete',
  FAILED: 'Failed',
}
