import { useEffect, useId, useRef, useState } from 'react'
import { AlertTriangle, ChevronDown, History, ImagePlus, Loader2, Sparkles, X } from 'lucide-react'
import { StatusBadge } from '../components/results/StatusBadge'
import { Button } from '../components/ui/Button'
import { ApiError, api, demoInspections, sampleFile } from '../lib/api'
import { navigate } from '../lib/router'
import type { ApiErrorDetail, SampleCase } from '../lib/types'
import { cn } from '../lib/utils'

// Mirrors backend guardrail defaults (app/guardrails/config.py). The backend stays the authority.
const MAX_FILES = 10
const MAX_FILE_BYTES = 10 * 1024 * 1024
const MIN_SIDE = 64
const LOW_RES_SIDE = 640
const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp']

type FileState = 'checking' | 'valid' | 'warning' | 'invalid'
type Role = 'before' | 'after'

interface SampleJob {
  work_order_text: string
  photos: { name: string; role: Role; url: string }[]
}

interface Photo {
  key: string
  role: Role
  file: File
  previewUrl: string
  state: FileState
  message?: string
}

const EXAMPLE = '- Install two outlet cover plates in the living room\n- Repair and repaint the damaged hallway wall\n- Seal the bathroom tub perimeter with caulk'

async function checkFile(file: File): Promise<Pick<Photo, 'state' | 'message'>> {
  if (!ACCEPTED_TYPES.includes(file.type)) return { state: 'invalid', message: 'Not a JPG, PNG or WebP image.' }
  if (file.size > MAX_FILE_BYTES) return { state: 'invalid', message: 'Larger than 10 MB.' }
  try {
    const bitmap = await createImageBitmap(file)
    const { width, height } = bitmap
    bitmap.close()
    if (width < MIN_SIDE || height < MIN_SIDE) return { state: 'invalid', message: `Too small (${width}×${height}).` }
    if (Math.min(width, height) < LOW_RES_SIDE) return { state: 'warning', message: `Low resolution (${width}×${height}); details may be hard to see.` }
    return { state: 'valid' }
  } catch {
    return { state: 'invalid', message: 'The file could not be opened as an image.' }
  }
}

function formatBytes(n: number) {
  return n < 1024 * 1024 ? `${Math.round(n / 1024)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`
}

export default function NewInspection() {
  const [workOrder, setWorkOrder] = useState('')
  const [photos, setPhotos] = useState<Photo[]>([])
  const [dragActive, setDragActive] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [workOrderError, setWorkOrderError] = useState<ApiErrorDetail | null>(null)
  const [formError, setFormError] = useState<ApiErrorDetail | null>(null)
  const [loadingSample, setLoadingSample] = useState<string | null>(null)
  const [cases, setCases] = useState<SampleCase[] | null>(null)
  const [showCases, setShowCases] = useState(false)
  const [usingSample, setUsingSample] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const beforeInputRef = useRef<HTMLInputElement>(null)
  const photosRef = useRef(photos)
  photosRef.current = photos
  const ids = { workOrder: useId(), workOrderHelp: useId(), workOrderError: useId(), photos: useId(), before: useId(), beforeHelp: useId(), cases: useId() }

  useEffect(() => () => photosRef.current.forEach((p) => URL.revokeObjectURL(p.previewUrl)), [])

  // replace: drop the current photos first (used by the samples)
  const addPhotos = (items: { file: File; role: Role }[], replace = false) => {
    setFormError(null)
    const incoming = items.slice(0, Math.max(0, MAX_FILES - (replace ? 0 : photos.length)))
    if (items.length > incoming.length) {
      setFormError({ code: 'TOO_MANY_FILES', message: `Up to ${MAX_FILES} photos per inspection.`, suggestion: 'Keep the photos that show the listed work.' })
    }
    if (replace) photosRef.current.forEach((p) => URL.revokeObjectURL(p.previewUrl))
    const added: Photo[] = incoming.map(({ file, role }) => ({
      key: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 7)}`,
      role,
      file,
      previewUrl: URL.createObjectURL(file),
      state: 'checking',
    }))
    setPhotos((prev) => (replace ? added : [...prev, ...added]))
    added.forEach(async (p) => {
      const result = await checkFile(p.file)
      setPhotos((prev) => prev.map((x) => (x.key === p.key ? { ...x, ...result } : x)))
    })
  }

  const addFiles = (list: FileList | File[], role: Role = 'after') => addPhotos(Array.from(list).map((file) => ({ file, role })))

  // demo: only the first sample job has a matching follow-up photo to offer on the report
  const loadSample = async (key: string, getSample: () => Promise<SampleJob>, demo = false) => {
    setLoadingSample(key)
    setFormError(null)
    setWorkOrderError(null)
    try {
      const sample = await getSample()
      const items = await Promise.all(sample.photos.map(async (p) => ({ file: await sampleFile(p.url, p.name), role: p.role })))
      setWorkOrder(sample.work_order_text)
      addPhotos(items, true)
      setUsingSample(demo)
      setShowCases(false)
    } catch (err) {
      setFormError(err instanceof ApiError ? err.details[0] : { code: 'UNKNOWN', message: 'Could not load the sample.' })
    } finally {
      setLoadingSample(null)
    }
  }
  const loadSingleSample = () => loadSample('single', async () => {
    const s = await api.samples()
    return { work_order_text: s.work_order_text, photos: s.photos.filter((p) => p.role === 'completion').map((p) => ({ ...p, role: 'after' as Role })) }
  }, true)
  const loadBeforeAfterSample = () => loadSample('before_after', async () => (await api.samples()).before_after)

  const toggleCases = async () => {
    setShowCases((v) => !v)
    if (cases) return
    try {
      setCases((await api.sampleCases()).cases)
    } catch (err) {
      setShowCases(false)
      setFormError(err instanceof ApiError ? err.details[0] : { code: 'UNKNOWN', message: 'Could not load the sample jobs.' })
    }
  }

  const removePhoto = (key: string) => {
    setPhotos((prev) => {
      const target = prev.find((p) => p.key === key)
      if (target) URL.revokeObjectURL(target.previewUrl)
      return prev.filter((p) => p.key !== key)
    })
    setFormError(null)
  }

  const usable = photos.filter((p) => p.state === 'valid' || p.state === 'warning')
  const usableAfter = usable.filter((p) => p.role === 'after')
  const usableBefore = usable.filter((p) => p.role === 'before')
  const afterPhotos = photos.filter((p) => p.role === 'after')
  const beforePhotos = photos.filter((p) => p.role === 'before')
  const checking = photos.some((p) => p.state === 'checking')
  const invalidCount = photos.filter((p) => p.state === 'invalid').length
  const hasWorkOrder = workOrder.trim().length > 0
  const canSubmit = hasWorkOrder && usableAfter.length > 0 && invalidCount === 0 && !checking && !submitting

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return
    setSubmitting(true)
    setWorkOrderError(null)
    setFormError(null)
    const submitted = { upload: usableAfter, before: usableBefore }
    try {
      const res = await api.createInspection(workOrder, usableAfter.map((p) => p.file), usableBefore.map((p) => p.file))
      if (usingSample) demoInspections.add(res.inspection_id)
      navigate(`/inspections/${res.inspection_id}`)
    } catch (err) {
      const details = err instanceof ApiError ? err.details : [{ code: 'UNKNOWN', message: 'Something went wrong.' }]
      let general: ApiErrorDetail | null = null
      const fileErrors = new Map<string, ApiErrorDetail>()
      for (const d of details) {
        if (d.field === 'work_order_text') setWorkOrderError(d)
        else if (d.file_id) {
          // upload_NN / before_NN is the 1-based position in that submitted list
          const [kind, n] = d.file_id.split('_')
          const target = submitted[kind as keyof typeof submitted]?.[Number(n) - 1]
          if (target) fileErrors.set(target.key, d)
        } else general ??= d
      }
      if (fileErrors.size) {
        setPhotos((prev) => prev.map((p) => (fileErrors.has(p.key) ? { ...p, state: 'invalid', message: fileErrors.get(p.key)!.message } : p)))
      }
      setFormError(general)
      setSubmitting(false)
    }
  }

  return (
    <main className="max-w-[1480px] mx-auto px-4 sm:px-6 lg:px-10 py-8 lg:py-12">
      <div className="max-w-3xl mb-8 lg:mb-10">
        <h1 className="font-display text-[34px] sm:text-[42px] leading-[1.05] tracking-tight text-ink">New inspection</h1>
        <p className="mt-3 text-[15px] text-ink-100 leading-relaxed">
          ProofLine compares each requirement in a work order with your completion photos, says what the photos support,
          and asks for a specific photo when they don't show enough.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <Button type="button" variant="outline" size="sm" onClick={loadSingleSample} disabled={!!loadingSample || submitting}>
            {loadingSample === 'single' ? <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden /> : <Sparkles className="w-3.5 h-3.5" aria-hidden />}
            Try it with a sample job
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={loadBeforeAfterSample} disabled={!!loadingSample || submitting}>
            {loadingSample === 'before_after' ? <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden /> : <History className="w-3.5 h-3.5" aria-hidden />}
            Try a before/after job
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={toggleCases} aria-expanded={showCases} aria-controls={ids.cases}>
            All sample jobs
            <ChevronDown className={cn('w-3.5 h-3.5 transition-transform', showCases && 'rotate-180')} aria-hidden />
          </Button>
          <span className="text-[12px] text-ink-50">Each fills in a work order and photos, so you can see a full report.</span>
        </div>
        {showCases && (
          <div id={ids.cases} className="mt-3 rounded-lg border border-ink/10 bg-paper/60">
            {!cases ? (
              <p className="px-4 py-3 text-[13px] text-ink-100 flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden />Loading sample jobs…</p>
            ) : (
              <>
                <p className="px-4 pt-3 pb-2 text-[12px] text-ink-50">
                  The {cases.length} labelled test cases from the evaluation. "Expected" is the label a careful coordinator gave each requirement.
                </p>
                <ul className="max-h-[360px] overflow-y-auto divide-y divide-ink/[0.07] border-t border-ink/[0.07]">
                  {cases.map((c) => {
                    const before = c.photos.filter((p) => p.role === 'before').length
                    const after = c.photos.length - before
                    return (
                      <li key={c.id}>
                        <button
                          type="button"
                          onClick={() => loadSample(c.id, async () => c)}
                          disabled={!!loadingSample || submitting}
                          className="w-full text-left px-4 py-2.5 flex flex-col sm:flex-row sm:items-center gap-1.5 sm:gap-4 hover:bg-ink/[0.03] disabled:opacity-60 focus-visible:outline-none focus-visible:bg-ink/[0.04]"
                        >
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-2 text-[13px] text-ink">
                              <span className="font-mono text-[11px] text-ink-50 tabular-nums">{c.id.slice(0, 2)}</span>
                              {c.title}
                              {loadingSample === c.id && <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden />}
                            </span>
                            <span className="block text-[12px] text-ink-100 truncate">
                              {c.work_order_text.split('\n').map((l) => l.replace(/^- /, '')).join(' · ')}
                            </span>
                          </span>
                          <span className="flex flex-wrap items-center gap-1.5 shrink-0">
                            <span className="text-[11px] text-ink-50">
                              {after} photo{after > 1 ? 's' : ''}{before ? ` + ${before} before` : ''}
                            </span>
                            <span className="text-[11px] text-ink-50 ml-1">Expected</span>
                            {c.expected.map((s, i) => <StatusBadge key={i} status={s} className="text-[11px] px-1.5" />)}
                          </span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </>
            )}
          </div>
        )}
      </div>

      {/* Mobile order: work order, photos, then checklist + submit. Desktop: photos fill the right column. */}
      <form onSubmit={submit} noValidate className="grid grid-cols-12 gap-x-6 lg:gap-x-10 gap-y-6 lg:grid-rows-[auto_1fr]">
        <section className="col-span-12 lg:col-span-5 lg:row-start-1 min-w-0" aria-label="Work order">
          <div>
            <div className="flex items-baseline justify-between mb-2">
              <label htmlFor={ids.workOrder} className="text-[14px] font-medium text-ink">Work order</label>
              {!hasWorkOrder && (
                <button type="button" onClick={() => setWorkOrder(EXAMPLE)} className="text-[12px] text-moss-300 hover:underline">
                  Use an example
                </button>
              )}
            </div>
            <p id={ids.workOrderHelp} className="text-[13px] text-ink-100 mb-2.5">One requirement per line. Include quantities where they matter.</p>
            <textarea
              id={ids.workOrder}
              value={workOrder}
              onChange={(e) => { setWorkOrder(e.target.value); setWorkOrderError(null); setUsingSample(false) }}
              placeholder={EXAMPLE}
              rows={8}
              aria-describedby={`${ids.workOrderHelp}${workOrderError ? ' ' + ids.workOrderError : ''}`}
              aria-invalid={!!workOrderError}
              className={cn(
                'w-full px-3.5 py-3 rounded-lg border bg-paper text-[14px] leading-relaxed text-ink placeholder:text-ink-50/70 resize-y outline-none transition-colors',
                'focus:ring-2 focus:ring-moss/25 focus:border-moss/50',
                workOrderError ? 'border-brick/60' : 'border-ink/15',
              )}
            />
            {workOrderError && (
              <div id={ids.workOrderError} role="alert" className="mt-2 text-[13px] text-brick-300">
                <p className="font-medium">{workOrderError.message}</p>
                {workOrderError.suggestion && <p className="text-brick-200/90 mt-0.5">{workOrderError.suggestion}</p>}
              </div>
            )}
          </div>
        </section>

        <section className="col-span-12 lg:col-span-5 lg:row-start-2 order-last lg:order-none space-y-6" aria-label="Review and run">
          <div className="rounded-lg border border-ink/10 bg-paper/60 px-4 py-3.5">
            <p className="text-[13px] font-medium text-ink mb-2">Before you run it</p>
            <ul className="space-y-1.5 text-[13px]">
              <ChecklistItem ok={hasWorkOrder}>Work order has at least one requirement</ChecklistItem>
              <ChecklistItem ok={usableAfter.length > 0}>At least one readable completion photo ({usable.length}/{MAX_FILES} photos in total)</ChecklistItem>
              <ChecklistItem ok={photos.length > 0 && invalidCount === 0 && !checking}>
                {invalidCount ? `Remove ${invalidCount} photo${invalidCount > 1 ? 's' : ''} that can't be used` : 'All photos are JPG, PNG or WebP under 10 MB'}
              </ChecklistItem>
            </ul>
            <p className="mt-3 text-[12px] text-ink-50 leading-relaxed">
              Results describe what the photos show. They don't certify safety, code compliance or hidden work.
            </p>
          </div>

          <div className="space-y-3">
            <Button type="submit" size="lg" className="w-full h-11 text-[14px]" disabled={!canSubmit}>
              {submitting ? (<><Loader2 className="w-4 h-4 animate-spin" />Checking the work order and photos…</>) : 'Run inspection'}
            </Button>
            {formError && (
              <div role="alert" className="flex gap-2.5 rounded-lg border border-brick/30 bg-brick/[0.06] px-3.5 py-3 text-[13px]">
                <AlertTriangle className="w-4 h-4 text-brick mt-0.5 shrink-0" aria-hidden />
                <div>
                  <p className="font-medium text-brick-300">{formError.message}</p>
                  {formError.suggestion && <p className="text-ink-100 mt-0.5">{formError.suggestion}</p>}
                </div>
              </div>
            )}
          </div>
        </section>

        <section className="col-span-12 lg:col-span-7 lg:col-start-6 lg:row-start-1 lg:row-span-2 min-w-0" aria-labelledby={ids.photos}>
          <div className="flex items-baseline justify-between mb-2">
            <h2 id={ids.photos} className="text-[14px] font-medium text-ink">Completion photos</h2>
            {photos.length > 0 && <span className="text-[12px] text-ink-50 tabular-nums">{photos.length} of {MAX_FILES}</span>}
          </div>
          <div
            onDragEnter={(e) => { e.preventDefault(); setDragActive(true) }}
            onDragOver={(e) => { e.preventDefault(); setDragActive(true) }}
            onDragLeave={(e) => { e.preventDefault(); setDragActive(false) }}
            onDrop={(e) => { e.preventDefault(); setDragActive(false); if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files) }}
            className={cn(
              'rounded-xl border-2 border-dashed transition-colors',
              dragActive ? 'border-moss/60 bg-moss/[0.06]' : 'border-ink/15 bg-paper/50',
            )}
          >
            <input
              ref={inputRef}
              type="file"
              multiple
              accept={ACCEPTED_TYPES.join(',')}
              onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = '' }}
              className="sr-only"
              tabIndex={-1}
              aria-hidden
            />
            {afterPhotos.length === 0 ? (
              <div className="px-6 py-16 sm:py-24 text-center">
                <ImagePlus className="w-7 h-7 mx-auto text-ink-50" strokeWidth={1.5} aria-hidden />
                <p className="mt-3 text-[15px] text-ink">Drop photos here</p>
                <p className="mt-1 text-[13px] text-ink-100">Wide shots for context, close-ups for detail. JPG, PNG or WebP, up to 10 MB each.</p>
                <Button type="button" variant="secondary" className="mt-5" onClick={() => inputRef.current?.click()}>Choose photos</Button>
              </div>
            ) : (
              <PhotoGrid photos={afterPhotos} onRemove={removePhoto} onAdd={photos.length < MAX_FILES ? () => inputRef.current?.click() : undefined} addLabel="Add photos" />
            )}
          </div>

          <div className="mt-6">
            <div className="flex items-baseline justify-between mb-1">
              <h2 id={ids.before} className="text-[14px] font-medium text-ink">Before photos <span className="font-normal text-ink-50">(optional)</span></h2>
              {beforePhotos.length > 0 && <span className="text-[12px] text-ink-50 tabular-nums">{beforePhotos.length}</span>}
            </div>
            <p id={ids.beforeHelp} className="text-[13px] text-ink-100 mb-2.5">
              For repairs and repainting. ProofLine checks that the after photos show the same place and what changed. Before photos are never evidence on their own.
            </p>
            <input
              ref={beforeInputRef}
              type="file"
              multiple
              accept={ACCEPTED_TYPES.join(',')}
              onChange={(e) => { if (e.target.files) addFiles(e.target.files, 'before'); e.target.value = '' }}
              className="sr-only"
              tabIndex={-1}
              aria-hidden
            />
            {beforePhotos.length === 0 ? (
              <button
                type="button"
                onClick={() => beforeInputRef.current?.click()}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files, 'before') }}
                disabled={photos.length >= MAX_FILES}
                aria-describedby={ids.beforeHelp}
                className="w-full rounded-xl border border-dashed border-ink/15 bg-paper/50 px-4 py-5 flex items-center justify-center gap-2 text-[13px] text-ink-100 hover:text-ink hover:border-ink/30 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-moss/40"
              >
                <History className="w-4 h-4" strokeWidth={1.5} aria-hidden />
                Add before photos
              </button>
            ) : (
              <div className="rounded-xl border border-dashed border-ink/15 bg-paper/50 p-3 sm:p-4" aria-labelledby={ids.before}>
                <PhotoGrid photos={beforePhotos} onRemove={removePhoto} onAdd={photos.length < MAX_FILES ? () => beforeInputRef.current?.click() : undefined} addLabel="Add before photos" tag="Before" />
              </div>
            )}
          </div>
        </section>
      </form>
    </main>
  )
}

function PhotoGrid({ photos, onRemove, onAdd, addLabel, tag }: {
  photos: Photo[]
  onRemove: (key: string) => void
  onAdd?: () => void
  addLabel: string
  tag?: string
}) {
  return (
    <ul className={cn('grid grid-cols-2 sm:grid-cols-3 gap-3', !tag && 'p-3 sm:p-4')}>
      {photos.map((p) => (
        <li key={p.key} className="group relative rounded-lg overflow-hidden border border-ink/10 bg-paper">
          <div className="aspect-[4/3] bg-chalk-200">
            <img src={p.previewUrl} alt="" className={cn('w-full h-full object-cover', p.state === 'invalid' && 'opacity-40 grayscale')} />
          </div>
          {tag && <span className="absolute top-2 left-2 px-1.5 rounded-sm bg-ink/80 text-white text-[11px] leading-5" aria-hidden>{tag}</span>}
          <div className="px-2.5 py-2">
            <p className="text-[12px] text-ink truncate" title={p.file.name}>{p.file.name}</p>
            <FileStatus photo={p} />
          </div>
          <button
            type="button"
            onClick={() => onRemove(p.key)}
            aria-label={`Remove ${p.file.name}`}
            className="absolute top-2 right-2 w-7 h-7 rounded-full bg-ink/70 text-white flex items-center justify-center hover:bg-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </li>
      ))}
      {onAdd && (
        <li>
          <button
            type="button"
            onClick={onAdd}
            className="w-full h-full min-h-[140px] rounded-lg border border-dashed border-ink/20 flex flex-col items-center justify-center gap-1.5 text-[13px] text-ink-100 hover:text-ink hover:border-ink/35 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-moss/40"
          >
            <ImagePlus className="w-5 h-5" strokeWidth={1.5} aria-hidden />
            {addLabel}
          </button>
        </li>
      )}
    </ul>
  )
}

function ChecklistItem({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2">
      <span
        aria-hidden
        className={cn('mt-[5px] w-2.5 h-2.5 rounded-full border shrink-0', ok ? 'bg-moss border-moss' : 'border-ink/30')}
      />
      <span className={ok ? 'text-ink' : 'text-ink-100'}>
        <span className="sr-only">{ok ? 'Done: ' : 'To do: '}</span>
        {children}
      </span>
    </li>
  )
}

function FileStatus({ photo }: { photo: Photo }) {
  if (photo.state === 'checking') return <p className="text-[11px] text-ink-50 mt-0.5">Checking…</p>
  if (photo.state === 'invalid') return <p className="text-[11px] text-brick-300 mt-0.5 leading-snug">{photo.message}</p>
  if (photo.state === 'warning') return <p className="text-[11px] text-amber-400 mt-0.5 leading-snug">{photo.message}</p>
  return <p className="text-[11px] text-ink-50 mt-0.5">{formatBytes(photo.file.size)} · ready</p>
}
