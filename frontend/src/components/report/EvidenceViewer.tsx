import { useState } from 'react'
import type { ReportImage, ReportObservation, ReportTask } from '../../lib/types'
import { cn } from '../../lib/utils'
import { statusConfig } from '../results/StatusBadge'

const IMAGE_STATE_NOTE: Record<string, string> = {
  IRRELEVANT: 'Judged unrelated to these requirements',
  LOW_QUALITY: 'Too dark or blurry to judge reliably',
  NOT_A_PHOTO: 'Not a photograph',
  FAILED: 'Could not be analyzed',
  PENDING: 'Not analyzed',
}

interface Props {
  images: ReportImage[]
  observations: ReportObservation[]
  activeImageId: string | null
  onSelectImage: (id: string) => void
  task: ReportTask | null
}

export function EvidenceViewer({ images, observations, activeImageId, onSelectImage, task }: Props) {
  const image = images.find((i) => i.id === activeImageId) ?? images[0]
  const [natural, setNatural] = useState<Record<string, { w: number; h: number }>>({})
  const [sideBySide, setSideBySide] = useState(true)
  if (!image) return null

  // The before photo this after photo was compared with, for the selected requirement.
  const comparedWith = task && observations.find((o) => o.source === 'comparison' && o.image_id === image.id && o.compared_with && o.task_ids.includes(task.id))?.compared_with
  const before = comparedWith ? images.find((i) => i.id === comparedWith) ?? null : null
  const showBefore = !!before && sideBySide
  const photoNumber = (img: ReportImage) => images.indexOf(img) + 1

  const size = natural[image.id] ?? (image.width && image.height ? { w: image.width, h: image.height } : null)
  // Only regions SAM returned for the selected task's evidence on this photo.
  const regions = task
    ? task.evidence.filter((e) => e.image_id === image.id).flatMap((e) => e.regions ?? [])
    : []
  const stroke = task ? statusConfig(task.status).stroke : '#202622'
  const evidenceImageIds = new Set(task?.evidence.map((e) => e.image_id) ?? [])
  const stateNote = image.analysis_state !== 'ANALYZED' ? IMAGE_STATE_NOTE[image.analysis_state] : null

  return (
    <div>
      <figure className="rounded-xl bg-ink overflow-hidden">
        <div className="flex items-center justify-center gap-2 sm:gap-3 p-2 sm:p-3 min-h-[240px] min-w-0">
          {showBefore && (
            <div className="relative inline-block max-w-[50%] min-w-0">
              <img src={before.url} alt={`Before photo ${before.filename ?? ''}`}
                className="block max-w-full max-h-[58vh] lg:max-h-[calc(100vh-290px)] w-auto h-auto rounded-md" />
              <span className="absolute top-2 left-2 px-1.5 rounded-sm bg-white/90 text-ink text-[11px] font-medium leading-5">Before · photo {photoNumber(before)}</span>
            </div>
          )}
          <div className={cn('relative inline-block min-w-0', showBefore ? 'max-w-[50%]' : 'max-w-full')}>
            <img
              src={image.url}
              alt={`Submitted photo ${image.filename ?? ''}`}
              onLoad={(e) => {
                const el = e.currentTarget
                setNatural((prev) => ({ ...prev, [image.id]: { w: el.naturalWidth, h: el.naturalHeight } }))
              }}
              className="block max-w-full max-h-[58vh] lg:max-h-[calc(100vh-290px)] w-auto h-auto rounded-md"
            />
            {showBefore && (
              <span className="absolute top-2 left-2 px-1.5 rounded-sm bg-white/90 text-ink text-[11px] font-medium leading-5 z-10">After · photo {photoNumber(image)}</span>
            )}
            {size && regions.length > 0 && (
              <svg
                className="absolute inset-0 w-full h-full pointer-events-none"
                viewBox={`0 0 ${size.w} ${size.h}`}
                preserveAspectRatio="none"
                aria-hidden
              >
                {regions.map((r, i) => {
                  const sx = size.w / r.image_width
                  const sy = size.h / r.image_height
                  const x = r.box.x1 * sx
                  const y = r.box.y1 * sy
                  const w = (r.box.x2 - r.box.x1 + 1) * sx
                  const h = (r.box.y2 - r.box.y1 + 1) * sy
                  const fontSize = Math.max(14, size.w / 70)
                  const labelW = (r.label.length * 0.56 + 1.2) * fontSize
                  return (
                    <g key={i}>
                      <rect x={x} y={y} width={w} height={h} fill={stroke} fillOpacity={0.12} stroke={stroke} strokeWidth={Math.max(3, size.w / 400)} rx={size.w / 300} />
                      <rect x={x} y={Math.max(0, y - fontSize * 1.6)} width={labelW} height={fontSize * 1.5} fill={stroke} rx={fontSize / 4} />
                      <text x={x + fontSize * 0.6} y={Math.max(0, y - fontSize * 1.6) + fontSize * 1.08} fill="#fff" fontSize={fontSize} fontFamily="Inter, sans-serif" fontWeight={600}>
                        {r.label}
                      </text>
                    </g>
                  )
                })}
              </svg>
            )}
          </div>
        </div>
        <figcaption className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-2.5 border-t border-white/10 text-[12px] text-white/70">
          <span className="truncate">
            {image.role === 'before' && <span className="text-white/90">Before photo · </span>}
            {image.follow_up_for && <span className="text-white/90">Follow-up photo · </span>}
            {image.filename ?? image.id}{size && <span className="text-white/45"> · {size.w}×{size.h}</span>}
          </span>
          {before && (
            <button type="button" onClick={() => setSideBySide((v) => !v)} aria-pressed={sideBySide}
              className="text-white/90 underline underline-offset-2 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60 rounded-sm">
              {sideBySide ? 'Hide before photo' : `Compare with before photo ${photoNumber(before)}`}
            </button>
          )}
          {image.role === 'before' ? (
            <span>Taken before the work. Used only to see what changed, never as evidence on its own.</span>
          ) : stateNote ? (
            <span className="text-amber-50">{stateNote}</span>
          ) : regions.length > 0 ? (
            <span>Boxes show objects located by SAM 3.1. A box marks where something is, not that the work is complete.</span>
          ) : task && evidenceImageIds.has(image.id) ? (
            <span>Cited as evidence for the selected requirement. No object location available.</span>
          ) : null}
        </figcaption>
      </figure>

      {images.length > 1 && (
        <ul className="mt-3 flex gap-2 overflow-x-auto pb-1" aria-label="Photos">
          {images.map((img, i) => (
            <li key={img.id} className="shrink-0">
              <button
                type="button"
                onClick={() => onSelectImage(img.id)}
                aria-pressed={img.id === image.id}
                aria-label={`Photo ${i + 1}${img.role === 'before' ? ', before the work' : ''}${img.follow_up_for ? ', follow-up' : ''}${evidenceImageIds.has(img.id) ? ', cited as evidence' : ''}`}
                className={cn(
                  'relative block w-24 h-[72px] rounded-md overflow-hidden border-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-moss/50',
                  img.id === image.id ? 'border-ink' : 'border-transparent opacity-70 hover:opacity-100',
                )}
              >
                <img src={img.url} alt="" className="w-full h-full object-cover" />
                {(img.follow_up_for || img.role === 'before') && (
                  <span className="absolute top-1 left-1 px-1 rounded-sm bg-ink/80 text-white text-[10px] leading-4" aria-hidden>
                    {img.role === 'before' ? 'Before' : 'Follow-up'}
                  </span>
                )}
                {evidenceImageIds.has(img.id) && (
                  <span className="absolute bottom-1 left-1 w-2.5 h-2.5 rounded-full border-2 border-white" style={{ background: stroke }} aria-hidden />
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
