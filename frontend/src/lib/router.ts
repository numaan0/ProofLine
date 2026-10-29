import { useEffect, useState } from 'react'

export type Route =
  | { name: 'new' }
  | { name: 'list' }
  | { name: 'inspection'; id: string; taskId?: string }

export function parseHash(hash: string): Route {
  const path = hash.replace(/^#/, '') || '/new'
  const [pathname, query = ''] = path.split('?')
  const match = pathname.match(/^\/inspections\/([\w-]+)$/)
  if (match) {
    const taskId = new URLSearchParams(query).get('task') ?? undefined
    return { name: 'inspection', id: match[1], taskId }
  }
  if (pathname === '/inspections') return { name: 'list' }
  return { name: 'new' }
}

export function navigate(path: string) {
  window.location.hash = path
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseHash(window.location.hash))
  useEffect(() => {
    const onChange = () => {
      setRoute(parseHash(window.location.hash))
      window.scrollTo(0, 0)
    }
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}
