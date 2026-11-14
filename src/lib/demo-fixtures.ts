const SYNTHETIC_DEMO_EMAIL = 'demo@croptwist.local'

/** True only for the development account whose seeded records are synthetic fixtures. */
export function isSyntheticDemoAccount(email: string | null | undefined): boolean {
  return email?.trim().toLowerCase() === SYNTHETIC_DEMO_EMAIL
}
