import { useMutation } from '@tanstack/react-query'
import { authApi } from '@/lib/api'
import { useAuthStore } from '@/store/authStore'
import type { LoginRequest, OtpVerifyRequest } from '@/types/auth'

export function useLogin() {
  return useMutation({
    mutationFn: (data: LoginRequest) => authApi.login(data),
  })
}

export function useVerifyOtp() {
  const setToken = useAuthStore((state) => state.setToken)
  return useMutation({
    mutationFn: (data: OtpVerifyRequest) => authApi.verifyOtp(data),
    onSuccess: (data) => {
      setToken(data.access_token)
    },
  })
}

export function useLogout() {
  const logout = useAuthStore((state) => state.logout)
  return useMutation({
    mutationFn: () => authApi.logout(),
    onSettled: () => logout(),
  })
}
