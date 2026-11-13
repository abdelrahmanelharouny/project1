'use client'

/**
 * P03 W2.1 — barrel for the six promoted Crop-management sub-pages
 * (blueprint §C2: management's internal 6-view switcher → six sub-pages of
 * Crop Intelligence). The former 1,239-line `management.tsx` container is
 * replaced by: `shared.tsx` (shell + honesty primitives) + one focused file
 * per view, each moved VERBATIM (same queries, mutations, forms, gating).
 */

import { CoversPage } from './cover-studio'
import { ErosionPage } from './erosion-view'
import { OperationsPage } from './operations-view'
import { PlanPage } from './plan-view'
import { ResiduePage } from './residue-view'
import { TimelinePage } from './timeline-view'

export {
  CoversPage,
  ErosionPage,
  OperationsPage,
  PlanPage,
  ResiduePage,
  TimelinePage,
}
