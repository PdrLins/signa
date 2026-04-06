export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  message: string
  session_token: string
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
