import type { CropHistoryItem } from '@/lib/types'

function yearFromDate(date: string | null): string | null {
  const match = date?.match(/^(\d{4})-/)
  return match?.[1] ?? null
}

/** Return only calendar years present in recorded sowing/harvest dates. */
export function cropHistoryYears(items: readonly CropHistoryItem[]): string[] {
  const years = items.flatMap((item) => [
    yearFromDate(item.sowing_date),
    yearFromDate(item.harvest_date),
  ])
  return Array.from(new Set(years.filter((year): year is string => year !== null)))
    .sort((left, right) => right.localeCompare(left))
}

/** Filter history by a year observed in either date; `all` preserves every row. */
export function cropHistoryForPeriod(
  items: readonly CropHistoryItem[],
  period: string,
): CropHistoryItem[] {
  if (period === 'all') return [...items]
  return items.filter((item) =>
    yearFromDate(item.sowing_date) === period || yearFromDate(item.harvest_date) === period,
  )
}
