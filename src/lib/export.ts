/**
 * P1 export pipeline: dependency-free client-side exports. Every export
 * composes rows in memory, serializes them (CSV with a UTF-8 BOM so Excel
 * opens Arabic content correctly, or pretty JSON) and triggers a download.
 */

export interface ExportColumn<T> {
  key: keyof T & string
  /** Column header (already localized by the caller). */
  label: string
}

function csvEscape(value: unknown): string {
  if (value === null || value === undefined) return ''
  const text = typeof value === 'string' ? value : String(value)
  if (/[",\n\r]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`
  }
  return text
}

export function toCsv<T extends Record<string, unknown>>(
  rows: T[],
  columns?: ExportColumn<T>[],
): string {
  if (rows.length === 0) return ''
  const cols: ExportColumn<T>[] =
    columns ?? (Object.keys(rows[0]) as (keyof T & string)[]).map((key) => ({ key, label: key }))
  const header = cols.map((col) => csvEscape(col.label)).join(',')
  const body = rows.map((row) => cols.map((col) => csvEscape(row[col.key])).join(',')).join('\n')
  // BOM: Excel detects UTF-8 (and renders Arabic headers) only with it.
  return `\uFEFF${header}\n${body}`
}

export function downloadText(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

/** Download rows as CSV. Filename should already include the extension. */
export function exportCsv<T extends Record<string, unknown>>(
  filename: string,
  rows: T[],
  columns?: ExportColumn<T>[],
): void {
  downloadText(filename, toCsv(rows, columns), 'text/csv')
}

/** Download an arbitrary JSON payload (single record or list). */
export function exportJson(filename: string, data: unknown): void {
  downloadText(filename, JSON.stringify(data, null, 2), 'application/json')
}

/** Timestamped filename helper: fields_North-2026-11-09.csv */
export function exportFilename(base: string, extension: 'csv' | 'json'): string {
  const safe = base.replace(/[^a-z0-9_-]+/gi, '-').replace(/^-+|-+$/g, '') || 'export'
  const day = new Date().toISOString().slice(0, 10)
  return `${safe}_${day}.${extension}`
}
