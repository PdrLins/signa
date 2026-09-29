export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  message: string
  // OTP flow: session_token is set → verify with /auth/verify-otp.
  // Password-only flow (LOGIN_OTP_ENABLED=false): access_token is set instead.
  session_token?: string | null
  access_token?: string | null
  last_login?: string
}

export interface OtpVerifyRequest {
  session_token: string
  otp_code: string
}

export interface AuthResponse {
  access_token: string
  token_type: string
  expires_in: number
  last_login?: string
}

export interface LogoutResponse {
  message: string
}
