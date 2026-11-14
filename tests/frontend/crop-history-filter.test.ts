/// <reference types="bun-types" />
import { describe, expect, test } from 'bun:test'

import { cropHistoryForPeriod, cropHistoryYears } from '@/lib/crop-history-filter'
import type { CropHistoryItem } from '@/lib/types'

function row(id: string, sowing: string | null, harvest: string | null): CropHistoryItem {
  return {
    id,
    crop_code: null,
    crop_label: `Recorded ${id}`,
    sowing_date: sowing,
    harvest_date: harvest,
    season_label: null,
    area_ha: null,
    source: 'field record',
    evidence_class: 'recorded',
  }
}

const history: CropHistoryItem[] = [
  row('a', '2024-10-01', '2025-02-03'),
  row('b', '2023-03-10', '2023-08-20'),
  row('c', null, null),
]

describe('crop history period filters', () => {
  test('year facets come only from recorded sowing/harvest dates, unique and newest first', () => {
    expect(cropHistoryYears(history)).toEqual(['2025', '2024', '2023'])
  })

  test('a record appears when either recorded date falls in the chosen year', () => {
    expect(cropHistoryForPeriod(history, '2025').map((item) => item.id)).toEqual(['a'])
    expect(cropHistoryForPeriod(history, '2024').map((item) => item.id)).toEqual(['a'])
    expect(cropHistoryForPeriod(history, '2023').map((item) => item.id)).toEqual(['b'])
    expect(cropHistoryForPeriod(history, '2022')).toEqual([])
  })

  test('all history includes undated rows and does not mutate the source array', () => {
    const result = cropHistoryForPeriod(history, 'all')
    expect(result).toEqual(history)
    expect(result).not.toBe(history)
    expect(history.map((item) => item.id)).toEqual(['a', 'b', 'c'])
  })
})
