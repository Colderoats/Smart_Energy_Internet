// Client-side mirror of backend/app/auth/passwords.py. The server is the
// authority; this only gives instant feedback. backend/tests/test_auth.py
// checks that COMMON_WORDS and the length limits match the backend's.

export const MIN_LENGTH = 12
export const MAX_LENGTH = 128

const COMMON_WORDS = [
  'password', 'passw0rd', 'qwerty', 'qwertyuiop', 'asdfgh', 'asdfghjkl', 'zxcvbnm',
  'letmein', 'welcome', 'iloveyou', 'admin', 'administrator', 'abc', 'abcdef',
  'abcdefgh', 'monkey', 'dragon', 'football', 'baseball', 'sunshine', 'princess',
  'master', 'shadow', 'superman', 'batman', 'trustno', 'whatever', 'freedom',
  'starwars', 'changeme', 'secret', 'login', 'hello', 'helloworld', 'test',
  'testing', 'default', 'root', 'user', 'guest', 'qazwsx', 'michael', 'charlie',
  'jennifer', 'computer', 'internet', 'energy', 'smartenergy', 'smartgrid',
]

const COMMON = new Set(COMMON_WORDS)
const DIGITS = '0123456789012345678901234567890'
const TOO_COMMON = 'This password is too common. Choose something less predictable.'

// Returns a reason the password is rejected, or null if it passes.
export function passwordProblem(password) {
  if (password.length < MIN_LENGTH) return `Password must be at least ${MIN_LENGTH} characters.`
  if (password.length > MAX_LENGTH) return `Password must be at most ${MAX_LENGTH} characters.`
  const lowered = password.toLowerCase()
  const letters = lowered.replace(/[^a-z]/g, '')
  if (COMMON.has(lowered) || (letters && COMMON.has(letters)) || (!letters && DIGITS.includes(lowered))) {
    return TOO_COMMON
  }
  if (new Set(lowered).size <= 3) return TOO_COMMON
  return null
}

export const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
