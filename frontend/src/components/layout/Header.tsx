import { cn } from '../../lib/utils'
import type { Route } from '../../lib/router'
import { NotificationBell } from './NotificationBell'

interface HeaderProps {
  route: Route
}

export function Header({ route }: HeaderProps) {
  const links = [
    { href: '#/inspections', label: 'Inspections', active: route.name === 'list' || route.name === 'inspection' },
    { href: '#/new', label: 'New inspection', active: route.name === 'new' },
  ]
  return (
    <header className="sticky top-0 z-40 bg-chalk/92 backdrop-blur-md border-b border-ink/10">
      <div className="max-w-[1480px] mx-auto px-4 sm:px-6 lg:px-10 h-14 flex items-center justify-between gap-4">
        <div className="flex items-center gap-6 sm:gap-10 min-w-0">
          <a href="#/new" className="font-display text-[15px] font-semibold tracking-[0.18em] text-ink shrink-0">
            PROOFLINE
          </a>
          <nav aria-label="Primary" className="flex items-center gap-1">
            {links.map((l) => (
              <a
                key={l.href}
                href={l.href}
                aria-current={l.active ? 'page' : undefined}
                className={cn(
                  'px-2.5 sm:px-3 py-1.5 rounded-md text-[13px] tracking-tight transition-colors whitespace-nowrap',
                  l.active ? 'text-ink bg-ink/[0.06] font-medium' : 'text-ink-100 hover:text-ink hover:bg-ink/[0.04]',
                )}
              >
                {l.label}
              </a>
            ))}
          </nav>
        </div>
        <NotificationBell />
      </div>
    </header>
  )
}
