/**
 * Entitlement guard (P3 §4.2 — server-enforced limits surface in UX).
 *
 * The backend is the only enforcement point (402 PAYMENT_REQUIRED with a
 * structured envelope naming the exhausted entitlement). This module turns
 * those responses into a consistent global UX signal: one toast with an
 * "Upgrade" action that navigates to the Billing tab.
 *
 * The three API clients (api.ts, api-p3-commercial.ts, api-p3-account.ts)
 * dispatch the `croptwist:payment-required` DOM event whenever a 402
 * envelope arrives; `mountEntitlementGuard()` registers ONE app-level
 * listener (workspace.tsx) so every gated surface — current and future —
 * gets the same treatment without per-component plumbing. Deduped so a
 * burst of blocked requests cannot spam toasts; re-subscribes on locale
 * change so the message always renders in the active language.
 */

export const PAYMENT_REQUIRED_EVENT = 'croptwist:payment-required'

export interface PaymentRequiredDetail {
  /** Stable entitlement key from the envelope, e.g. 'max_farms'. */
  entitlement?: string
  /** Server-provided human message (already localized server-side when possible). */
  message?: string
}

/** Dispatched by the API clients when the server answers 402. */
export function emitPaymentRequired(detail: PaymentRequiredDetail): void {
  if (typeof window === 'undefined' || typeof CustomEvent === 'undefined') return
  window.dispatchEvent(new CustomEvent<PaymentRequiredDetail>(PAYMENT_REQUIRED_EVENT, { detail }))
}

/**
 * Register the app-level listener. `onUpgrade` receives the entitlement
 * detail and typically shows a translated toast + navigates to Billing.
 * Returns an unmount function. No-op outside the browser (SSR).
 */
export function mountEntitlementGuard(
  onUpgrade: (detail: PaymentRequiredDetail) => void,
): () => void {
  if (typeof window === 'undefined' || typeof CustomEvent === 'undefined') return () => {}
  let lastAt = 0
  const DEDUPE_MS = 6000
  const handler = (event: Event): void => {
    const now = Date.now()
    if (now - lastAt < DEDUPE_MS) return
    lastAt = now
    const detail =
      (event as CustomEvent<PaymentRequiredDetail>).detail ?? {}
    onUpgrade(detail)
  }
  window.addEventListener(PAYMENT_REQUIRED_EVENT, handler)
  return () => window.removeEventListener(PAYMENT_REQUIRED_EVENT, handler)
}
