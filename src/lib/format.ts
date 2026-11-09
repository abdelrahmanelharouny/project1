/** Presentation helpers shared across FieldShift components. */

/** Format hectares with the active UI locale (falls back to runtime locale). */
export function formatArea(ha: number | null | undefined, locale?: string): string {
  if (ha === null || ha === undefined || Number.isNaN(ha)) return '—'
  return ha.toLocaleString(locale || undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function formatDay(iso: string | null | undefined): string {
  if (!iso) return '—'
  return iso.slice(0, 10)
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toISOString().replace('T', ' ').slice(0, 16) + ' UTC'
}

/** "air_temperature_mean" → "Air temperature mean" */
export function humanizeCode(code: string): string {
  return code
    .split('_')
    .map((part) => (part.length > 0 ? part[0].toUpperCase() + part.slice(1) : part))
    .join(' ')
}

export function pct(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined || Number.isNaN(ratio)) return '—'
  return `${Math.round(ratio * 100)}%`
}
