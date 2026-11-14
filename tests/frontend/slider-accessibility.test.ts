import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test } from 'bun:test'

import { Slider } from '@/components/ui/slider'

describe('shared Slider accessibility', () => {
  test('exposes the translated label and value text on the actual slider thumb', () => {
    const markup = renderToStaticMarkup(
      createElement(Slider, {
        min: 0,
        max: 100,
        value: [70],
        onValueChange: () => undefined,
        'aria-label': 'Layer opacity',
        'aria-valuetext': '70%',
      }),
    )
    const roleStart = markup.indexOf('role="slider"')
    expect(roleStart).toBeGreaterThanOrEqual(0)
    const thumb = markup.slice(roleStart, markup.indexOf('>', roleStart) + 1)
    expect(thumb).toContain('aria-label="Layer opacity"')
    expect(thumb).toContain('aria-valuetext="70%"')
  })
})
