'use client'

import dynamic from 'next/dynamic'
import { Sprout } from 'lucide-react'

/**
 * The workspace is loaded client-side only (ssr: false) so maplibre-gl never
 * executes during SSR. Everything visible lives in the single `/` route.
 */
const Workspace = dynamic(() => import('@/components/fieldshift/workspace'), {
  ssr: false,
  loading: () => (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-stone-50 text-stone-500">
      <Sprout className="h-8 w-8 animate-pulse text-emerald-700" aria-hidden />
      <p className="text-sm">Loading FieldShift workspace…</p>
    </div>
  ),
})

export default function Page() {
  return <Workspace />
}
