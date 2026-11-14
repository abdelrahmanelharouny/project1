import type { AuthSession, RegisterResult, RegistrationVerificationRequired } from './types'

function isVerificationRequired(result: RegisterResult): result is RegistrationVerificationRequired {
  return 'status' in result && result.status === 'verification_required'
}

/** Route registration responses to verification or authenticated UI behavior. */
export function handleRegistrationResult(
  result: RegisterResult,
  handlers: {
    onVerificationRequired: (email: string) => void
    onAuthenticated: (session: AuthSession) => void
  },
): void {
  if (isVerificationRequired(result)) {
    handlers.onVerificationRequired(result.user.email)
    return
  }

  handlers.onAuthenticated(result)
}
