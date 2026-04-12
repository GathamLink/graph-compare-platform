import { create } from 'zustand'
import { diffApi } from '@/api/diffApi'
import type { DiffStatusResponse, DiffPairResponse } from '@/types'

interface CompareStore {
  currentPairIndex: number
  viewMode: 'side-by-side' | 'slider'
  showDiff: boolean
  diffStatus: DiffStatusResponse | null
  currentPairData: DiffPairResponse | null
  pairLoading: boolean
  zoom: number
  setCurrentPair: (index: number) => void
  setViewMode: (mode: 'side-by-side' | 'slider') => void
  toggleDiff: () => void
  setZoom: (zoom: number) => void
  fetchPair: (taskId: number, pairIndex: number) => Promise<void>
  fetchStatus: (taskId: number) => Promise<DiffStatusResponse | null>
  startPolling: (taskId: number) => () => void
  reset: () => void
}

export const useCompareStore = create<CompareStore>((set, get) => ({
  currentPairIndex: 0,
  viewMode: 'side-by-side',
  showDiff: false,
  diffStatus: null,
  currentPairData: null,
  pairLoading: false,
  zoom: 1,

  reset: () => set({
    currentPairIndex: 0,
    diffStatus: null,
    currentPairData: null,
    pairLoading: false,
    zoom: 1,
  }),

  setCurrentPair: (index) => set({ currentPairIndex: index }),
  setViewMode: (mode) => set({ viewMode: mode }),
  toggleDiff: () => set((s) => ({ showDiff: !s.showDiff })),
  setZoom: (zoom) => set({ zoom }),

  fetchPair: async (taskId, pairIndex) => {
    set({ pairLoading: true })
    try {
      const data = await diffApi.pair(taskId, pairIndex)
      set({ currentPairData: data, pairLoading: false })
    } catch {
      set({ pairLoading: false })
    }
  },

  fetchStatus: async (taskId) => {
    try {
      const status = await diffApi.status(taskId)
      set({ diffStatus: status })
      return status
    } catch {
      return null
    }
  },

  startPolling: (taskId) => {
    const { fetchStatus } = get()
    let timer: ReturnType<typeof setInterval> | null = null
    let stopped = false

    const tick = async () => {
      if (stopped) return
      const s = await fetchStatus(taskId)
      // 全部完成或失败（无 pending/running）→ 停止轮询，刷新当前对
      if (s && s.pending === 0 && s.running === 0) {
        if (timer) clearInterval(timer)
        timer = null
        // 仅在完成时刷新一次当前配对数据
        get().fetchPair(taskId, get().currentPairIndex)
      }
    }

    // 立即拉一次 status（不拉 pair，pair 由 CompareViewPage 的 useEffect 负责）
    fetchStatus(taskId).then((s) => {
      if (!s) return
      // 已有计算任务才启动轮询，否则不需要
      if (s.pending > 0 || s.running > 0) {
        // 5s 间隔，减少后端压力
        timer = setInterval(tick, 5000)
      }
    })

    return () => {
      stopped = true
      if (timer) clearInterval(timer)
    }
  },
}))
