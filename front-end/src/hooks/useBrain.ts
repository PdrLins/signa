import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { client } from '@/lib/api'
import { useBrainStore } from '@/store/brainStore'

export interface BrainHighlights {
  active_rules: number
  blocker_count: number
  safe_income_rules: number
  high_risk_rules: number
  total_knowledge: number
  rules_by_type: Record<string, number>
  last_rule_updated: string | null
}

export function useBrainHighlights() {
  return useQuery({
    queryKey: ['brain', 'highlights'],
    queryFn: async () => {
      const res = await client.get('/brain/highlights')
      return res.data as BrainHighlights
    },
    staleTime: 30 * 1000,
  })
}

export function useBrainChallenge() {
  return useMutation({
    mutationFn: async () => {
      const res = await client.post('/brain/challenge')
      return res.data as { message: string; session_token: string }
    },
  })
}

export function useBrainVerify() {
  const setBrainToken = useBrainStore((s) => s.setBrainToken)
  return useMutation({
    mutationFn: async (otp_code: string) => {
      const res = await client.post('/brain/verify', { otp_code })
      return res.data as { brain_token: string; expires_in: number }
    },
    onSuccess: (data) => {
      setBrainToken(data.brain_token, data.expires_in)
    },
  })
}

function brainHeaders() {
  return useBrainStore.getState().getHeaders()
}

export function useBrainRules() {
  const isUnlocked = useBrainStore((s) => s.isUnlocked)
  return useQuery({
    queryKey: ['brain', 'rules'],
    queryFn: async () => {
      const res = await client.get('/brain/rules', { headers: brainHeaders() })
      return res.data as Record<string, unknown>[]
    },
    enabled: isUnlocked,
    staleTime: 0,
  })
}

export function useUpdateRule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: Record<string, unknown> }) => {
      const res = await client.put(`/brain/rules/${id}`, data, { headers: brainHeaders() })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['brain', 'rules'] })
      queryClient.invalidateQueries({ queryKey: ['brain', 'highlights'] })
    },
  })
}

export function useBrainKnowledge() {
  const isUnlocked = useBrainStore((s) => s.isUnlocked)
  return useQuery({
    queryKey: ['brain', 'knowledge'],
    queryFn: async () => {
      const res = await client.get('/brain/knowledge', { headers: brainHeaders() })
      return res.data as Record<string, unknown>[]
    },
    enabled: isUnlocked,
    staleTime: 0,
  })
}

export function useUpdateKnowledge() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: Record<string, unknown> }) => {
      const res = await client.put(`/brain/knowledge/${id}`, data, { headers: brainHeaders() })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['brain', 'knowledge'] })
      queryClient.invalidateQueries({ queryKey: ['brain', 'highlights'] })
    },
  })
}

// ── Self-Learning ──

export function useBrainSuggestions(status?: string) {
  const isUnlocked = useBrainStore((s) => s.isUnlocked)
  return useQuery({
    queryKey: ['brain', 'suggestions', status],
    queryFn: async () => {
      const params: Record<string, unknown> = {}
      if (status) params.status = status
      const res = await client.get('/learning/suggestions', { headers: brainHeaders(), params })
      return res.data as Record<string, unknown>[]
    },
    enabled: isUnlocked,
    staleTime: 0,
  })
}

export function useRunAnalysis() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (days: number = 7) => {
      const res = await client.post(`/learning/analyze?days=${days}`, null, { headers: brainHeaders() })
      return res.data as { suggestions: Record<string, unknown>[]; count: number }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['brain', 'suggestions'] })
    },
  })
}

export function useApproveSuggestion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      const res = await client.put(`/learning/suggestions/${id}/approve`, null, { headers: brainHeaders() })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['brain', 'suggestions'] })
    },
  })
}

export function useRejectSuggestion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, reason }: { id: string; reason?: string }) => {
      const res = await client.put(`/learning/suggestions/${id}/reject`, { reason }, { headers: brainHeaders() })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['brain', 'suggestions'] })
    },
  })
}

export function useApplySuggestion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      const res = await client.post(`/learning/suggestions/${id}/apply`, null, { headers: brainHeaders() })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['brain', 'suggestions'] })
      queryClient.invalidateQueries({ queryKey: ['brain', 'rules'] })
    },
  })
}

export function useBrainAudit() {
  const isUnlocked = useBrainStore((s) => s.isUnlocked)
  return useQuery({
    queryKey: ['brain', 'audit'],
    queryFn: async () => {
      const res = await client.get('/brain/audit', { headers: brainHeaders() })
      return res.data as Record<string, unknown>[]
    },
    enabled: isUnlocked,
    staleTime: 0,
  })
}
