import type {
  ApiErrorDetail,
  AppNotification,
  InspectionListItem,
  InspectionStatus,
  Report,
  SampleCase,
} from './types'

export class ApiError extends Error {
  status: number
  details: ApiErrorDetail[]

  constructor(status: number, details: ApiErrorDetail[]) {
    super(details[0]?.message ?? `Request failed (${status})`)
    this.status = status
    this.details = details
  }
}

const NETWORK_ERROR: ApiErrorDetail = {
  code: 'NETWORK_ERROR',
  message: 'Could not reach the ProofLine server.',
  suggestion: 'Check that the backend is running, then try again.',
  retryable: true,
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch {
    throw new ApiError(0, [NETWORK_ERROR])
  }
  if (res.ok) return res.json() as Promise<T>

  // Backend contract: {"error": {...}, "errors": [...]}; FastAPI 404s use {"detail": {...}}.
  let body: any = null
  try {
    body = await res.json()
  } catch {
    /* non-JSON error body */
  }
  const details: ApiErrorDetail[] =
    body?.errors?.length ? body.errors
      : body?.error ? [body.error]
        : body?.detail?.message ? [body.detail]
          : [{ code: 'HTTP_' + res.status, message: `Request failed (${res.status}).`, retryable: res.status >= 500 }]
  throw new ApiError(res.status, details)
}

export const api = {
  createInspection(workOrder: string, files: File[], beforeFiles: File[] = []) {
    const form = new FormData()
    form.append('work_order_text', workOrder)
    files.forEach((f) => form.append('files', f))
    beforeFiles.forEach((f) => form.append('before_files', f))
    return request<{ inspection_id: string; status: string }>('/api/inspections', { method: 'POST', body: form })
  },
  addFollowUpPhotos(inspectionId: string, taskId: string, files: File[]) {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return request<{ status: string; image_ids: string[] }>(
      `/api/inspections/${inspectionId}/tasks/${taskId}/follow-up-photos`,
      { method: 'POST', body: form },
    )
  },
  samples: () => request<{
    work_order_text: string
    photos: { name: string; role: 'completion' | 'follow_up'; url: string }[]
    before_after: { work_order_text: string; photos: { name: string; role: 'before' | 'after'; url: string }[] }
  }>('/api/samples'),
  sampleCases: () => request<{ cases: SampleCase[] }>('/api/samples/cases'),
  retry: (id: string) => request<{ status: string }>(`/api/inspections/${id}/retry`, { method: 'POST' }),
  inspection: (id: string) => request<InspectionStatus>(`/api/inspections/${id}`),
  report: (id: string) => request<Report>(`/api/inspections/${id}/report`),
  inspections: () => request<{ inspections: InspectionListItem[] }>('/api/inspections'),
  notifications: () => request<{ unread_count: number; notifications: AppNotification[] }>('/api/notifications'),
  markRead: (id: string) => request(`/api/notifications/${id}/read`, { method: 'POST' }),
  markAllRead: () => request('/api/notifications/read-all', { method: 'POST' }),
}

/** Download a bundled sample photo as a File, ready for upload. */
export async function sampleFile(url: string, name: string): Promise<File> {
  let res: Response
  try {
    res = await fetch(url)
  } catch {
    throw new ApiError(0, [NETWORK_ERROR])
  }
  if (!res.ok) throw new ApiError(res.status, [{ code: 'SAMPLE_UNAVAILABLE', message: 'The sample photo could not be loaded.' }])
  return new File([await res.blob()], name, { type: res.headers.get('content-type') ?? 'image/png' })
}

// Inspections started from the sample, so the report can offer the sample follow-up photo.
// Browser storage is a convenience only; every read and write tolerates it being unavailable.
const DEMO_KEY = 'proofline.demoInspections'
export const demoInspections = {
  has(id: string) {
    try {
      return (JSON.parse(localStorage.getItem(DEMO_KEY) ?? '[]') as string[]).includes(id)
    } catch {
      return false
    }
  },
  add(id: string) {
    try {
      const ids = JSON.parse(localStorage.getItem(DEMO_KEY) ?? '[]') as string[]
      localStorage.setItem(DEMO_KEY, JSON.stringify([id, ...ids].slice(0, 20)))
    } catch {
      /* storage unavailable */
    }
  },
}

export const TERMINAL_STATUSES = new Set(['COMPLETED', 'NEEDS_USER_ACTION', 'FAILED'])
