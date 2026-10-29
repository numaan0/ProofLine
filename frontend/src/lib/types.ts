export type TaskStatus = 'DONE' | 'MISSING' | 'CANT_TELL' | 'PENDING'

export type LifecycleStatus =
  | 'QUEUED'
  | 'PLANNING'
  | 'ANALYZING'
  | 'COMPARING'
  | 'VERIFYING'
  | 'INVESTIGATING'
  | 'GROUNDING'
  | 'REVERIFYING'
  | 'NEEDS_USER_ACTION'
  | 'COMPLETED'
  | 'FAILED'

export type OverallOutcome = 'ATTENTION_REQUIRED' | 'EVIDENCE_INCOMPLETE' | 'NO_FLAGGED_ISSUES' | null

export interface Counts {
  done: number
  missing: number
  cant_tell: number
}

export interface InspectionStatus {
  inspection_id: string
  title: string | null
  status: LifecycleStatus
  overall_outcome: OverallOutcome
  summary: string | null
  error: { code: string; message: string } | null
  tasks_count: number
  images_count: number
  counts: Counts
  created_at: string
  updated_at: string
}

export interface Region {
  label: string
  box: { x1: number; y1: number; x2: number; y2: number }
  image_width: number
  image_height: number
  confidence: number | null
  source: string
}

export interface Evidence {
  image_id: string
  observation_id: string
  regions: Region[] | null
  region_source: string | null
}

export interface ReportTask {
  id: string
  description: string
  observable_criteria: string | null
  status: TaskStatus
  reasoning: string | null
  observation_ids: string[]
  evidence: Evidence[]
  follow_up: {
    id: string
    needed: boolean
    request: string
    status: 'PENDING' | 'CHECKING' | 'RESOLVED' | string
    last_error: string | null
    image_ids: string[]
  } | null
  investigation: InvestigationStep[]
}

export interface InvestigationStep {
  tool: 'look_closer' | 'count_objects' | 'finalize' | 'investigation' | string
  args: Record<string, unknown>
  ok: boolean
  result: string
  ms: number
  round?: 'follow_up' | null
}

export interface ReportImage {
  id: string
  filename: string | null
  width: number | null
  height: number | null
  analysis_state: string
  follow_up_for: string | null
  role: 'before' | 'after'
  url: string
}

export interface ReportObservation {
  id: string
  image_id: string | null
  task_ids: string[]
  source: 'comparison' | 'investigation' | 'follow_up' | null
  compared_with: string | null
  text: string
  limitations: string | null
}

export interface Report {
  inspection_id: string
  title: string | null
  work_order_text: string
  status: LifecycleStatus
  overall_outcome: OverallOutcome
  summary: string | null
  error: { code: string; message: string } | null
  counts: Counts
  created_at: string
  images: ReportImage[]
  observations: ReportObservation[]
  tasks: ReportTask[]
}

export interface InspectionListItem {
  inspection_id: string
  title: string | null
  status: LifecycleStatus
  overall_outcome: OverallOutcome
  created_at: string
  counts: Counts
  needs_action: boolean
}

export interface AppNotification {
  id: string
  inspection_id: string | null
  inspection_title: string | null
  type: string
  title: string
  message: string
  read: boolean
  created_at: string
}

export interface ApiErrorDetail {
  code: string
  stage?: string
  message: string
  suggestion?: string
  retryable?: boolean
  field?: string
  file_id?: string
}

/** A labelled evaluation case offered as a sample job (data/eval/cases.json). */
export interface SampleCase {
  id: string
  title: string
  work_order_text: string
  photos: { name: string; role: 'before' | 'after'; url: string }[]
  expected: ('DONE' | 'MISSING' | 'CANT_TELL')[]
}
