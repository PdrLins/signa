import { useToastStore } from '@/store/toastStore'

export function useToast() {
  return {
    show: useToastStore((s) => s.show),
    dismiss: useToastStore((s) => s.dismiss),
  }
}
