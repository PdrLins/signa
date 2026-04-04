import { create } from 'zustand'

export type ToastVariant = 'success' | 'error' | 'warning' | 'info'

export interface Toast {
  id: string
  message: string
  variant: ToastVariant
  duration: number
}

interface ToastStore {
  toasts: Toast[]
  show: (message: string, variant?: ToastVariant, duration?: number) => void
  dismiss: (id: string) => void
}

let counter = 0

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],

  show: (message, variant = 'info', duration = 4000) => {
    const id = `toast-${++counter}`
    set((state) => ({
      toasts: [...state.toasts, { id, message, variant, duration }],
    }))
    setTimeout(() => {
      set((state) => ({
        toasts: state.toasts.filter((t) => t.id !== id),
      }))
    }, duration)
  },

  dismiss: (id) => {
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    }))
  },
}))
