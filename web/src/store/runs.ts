import { create } from 'zustand'
import { api, type RunConfig } from '../lib/api'

interface RunSummary {
  id: string
  ticker: string
  analysis_date: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  created_at: string
  completed_at?: string
  error_message?: string
}

interface RunDetail extends RunSummary {
  config: RunConfig
  report?: any
}

interface RunsState {
  runs: RunSummary[]
  total: number
  loading: boolean
  error: string | null
  selectedRun: RunDetail | null
  fetchHistory: (params?: { limit?: number; offset?: number; status?: string }) => Promise<void>
  fetchRun: (runId: string) => Promise<void>
  clearSelection: () => void
}

export const useRunsStore = create<RunsState>((set, get) => ({
  runs: [],
  total: 0,
  loading: false,
  error: null,
  selectedRun: null,

  fetchHistory: async (params) => {
    set({ loading: true, error: null })
    try {
      const data = await api.getHistory(params)
      set({ runs: data.runs, total: data.total, loading: false })
    } catch (e: any) {
      set({ error: e.message, loading: false })
    }
  },

  fetchRun: async (runId) => {
    set({ loading: true, error: null })
    try {
      const run = await api.getReport(runId)
      set({ selectedRun: run, loading: false })
    } catch (e: any) {
      set({ error: e.message, loading: false })
    }
  },

  clearSelection: () => set({ selectedRun: null }),
}))