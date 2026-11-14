/**
 * Server-only API origin configuration.
 *
 * This module must only be imported by Next configuration or server route
 * handlers. Browser code intentionally uses relative `/api/v1` paths so the
 * backend origin and any credentials never enter the client bundle.
 */

const LOCAL_API_ORIGIN = 'http://127.0.0.1:3030'
const HTTP_PROTOCOLS = new Set(['http:', 'https:'])

export class ApiOriginConfigurationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ApiOriginConfigurationError'
  }
}

/**
 * Validate and normalize a backend origin. Only an origin is accepted:
 * credentials, query strings, fragments, and path prefixes are rejected.
 */
export function validateApiOrigin(value: string): string {
  const raw = value.trim()
  if (!raw) throw new ApiOriginConfigurationError('CROPTWIST_API_ORIGIN must not be empty.')

  let parsed: URL
  try {
    parsed = new URL(raw)
  } catch {
    throw new ApiOriginConfigurationError(
      'CROPTWIST_API_ORIGIN must be an absolute http(s) origin.',
    )
  }

  if (!HTTP_PROTOCOLS.has(parsed.protocol)) {
    throw new ApiOriginConfigurationError(
      'CROPTWIST_API_ORIGIN must use the http or https protocol.',
    )
  }
  if (parsed.username || parsed.password) {
    throw new ApiOriginConfigurationError(
      'CROPTWIST_API_ORIGIN must not contain credentials.',
    )
  }
  if (parsed.search || parsed.hash) {
    throw new ApiOriginConfigurationError(
      'CROPTWIST_API_ORIGIN must not contain a query string or fragment.',
    )
  }
  if (parsed.pathname !== '/' && parsed.pathname !== '') {
    throw new ApiOriginConfigurationError(
      'CROPTWIST_API_ORIGIN must contain only a scheme, host, and optional port.',
    )
  }

  return parsed.origin
}

/**
 * Resolve the configured backend origin. Vercel must be explicitly
 * configured; the loopback fallback is intentionally limited to local/non-
 * Vercel execution so a hosted deployment cannot silently target localhost.
 */
export function resolveApiOrigin(
  configuredOrigin: string | undefined,
  options: { isVercel: boolean } = { isVercel: false },
): string {
  if (configuredOrigin?.trim()) {
    const origin = validateApiOrigin(configuredOrigin)
    if (options.isVercel && !origin.startsWith('https://')) {
      throw new ApiOriginConfigurationError('Vercel API origins must use HTTPS.')
    }
    return origin
  }
  if (options.isVercel) {
    throw new ApiOriginConfigurationError(
      'CROPTWIST_API_ORIGIN is required for Vercel deployments.',
    )
  }
  return LOCAL_API_ORIGIN
}

export function getApiOrigin(): string {
  return resolveApiOrigin(process.env.CROPTWIST_API_ORIGIN, {
    isVercel: process.env.VERCEL === '1' || process.env.VERCEL === 'true',
  })
}

export function getApiBase(): string {
  return `${getApiOrigin()}/api/v1`
}
