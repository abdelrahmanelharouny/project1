'use client'

import { useEffect } from 'react'

/**
 * Global error boundary (P2) — last resort when the root layout itself
 * crashes. It renders its own <html>/<body> (the root layout is bypassed),
 * so styling is intentionally inline: no external CSS is guaranteed here.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('[croptwist/web] global error', {
      digest: error.digest,
      message: error.message,
    })
  }, [error])

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#fafafa',
          color: '#18181b',
          fontFamily:
            "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
        }}
      >
        <div
          role="alert"
          style={{
            maxWidth: 420,
            padding: 24,
            textAlign: 'center',
          }}
        >
          <h1 style={{ fontSize: 18, fontWeight: 600, margin: '0 0 8px' }}>
            Critical error
          </h1>
          <p style={{ fontSize: 14, color: '#71717a', margin: '0 0 8px' }}>
            The application failed to start. Please reload the page.
          </p>
          {error.digest ? (
            <p style={{ fontSize: 12, color: '#a1a1aa', margin: '0 0 16px' }}>
              Error reference: {error.digest}
            </p>
          ) : null}
          <button
            onClick={reset}
            style={{
              minHeight: 44,
              padding: '0 16px',
              borderRadius: 8,
              border: '1px solid #d4d4d8',
              background: '#18181b',
              color: '#fafafa',
              fontSize: 14,
              cursor: 'pointer',
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  )
}
