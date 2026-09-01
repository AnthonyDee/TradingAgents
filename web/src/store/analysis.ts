import { create } from 'zustand'

export interface ToolCall {
  name: string
  args: Record<string, any>
  timestamp: string
}

export interface Message {
  type: string
  content: string
  timestamp: string
}

export interface ReportSection {
  section: string
  content: string
  timestamp: string
}

export interface Stats {
  llm_calls: number
  tool_calls: number
  tokens_in: number
  tokens_out: number
}

interface AgentStatus {
  [agent: string]: 'pending' | 'in_progress' | 'completed' | 'error'
}

interface AnalysisState {
  // Agent status
  agentStatus: AgentStatus
  setAgentStatus: (agent: string, status: AgentStatus[keyof AgentStatus]) => void

  // Tool calls
  toolCalls: ToolCall[]
  addToolCall: (name: string, args: Record<string, any>) => void

  // Messages
  messages: Message[]
  addMessage: (type: string, content: string) => void

  // Report sections
  reportSections: Record<string, string>
  updateReportSection: (section: string, content: string) => void

  // Stats
  stats: Stats
  updateStats: (stats: Partial<Stats>) => void

  // Timer
  startTime: string | null
  setStartTime: (time: string) => void

  // Completion
  completed: boolean
  runId: string | null
  error: string | null
  setComplete: (runId: string) => void
  setError: (error: string) => void
  markAllAgentsComplete: () => void

  // Reset
  reset: () => void
}

const initialState = {
  agentStatus: {} as AgentStatus,
  toolCalls: [] as ToolCall[],
  messages: [] as Message[],
  reportSections: {} as Record<string, string>,
  stats: { llm_calls: 0, tool_calls: 0, tokens_in: 0, tokens_out: 0 },
  startTime: null,
  completed: false,
  runId: null,
  error: null,
}

export const useAnalysisStore = create<AnalysisState>()((set) => ({
  ...initialState,

  setAgentStatus: (agent, status) => set((state) => ({
    agentStatus: { ...state.agentStatus, [agent]: status },
  })),

  addToolCall: (name, args) => set((state) => ({
    toolCalls: [
      { name, args, timestamp: new Date().toISOString() },
      ...state.toolCalls.slice(0, 99),
    ],
  })),

  addMessage: (type, content) => set((state) => ({
    messages: [
      { type, content, timestamp: new Date().toISOString() },
      ...state.messages.slice(0, 99),
    ],
  })),

  updateReportSection: (section, content) => set((state) => ({
    reportSections: { ...state.reportSections, [section]: content },
  })),

  updateStats: (stats) => set((state) => ({
    stats: { ...state.stats, ...stats },
  })),

  setComplete: (runId) => set({ completed: true, runId, error: null }),

  setStartTime: (time: string) => set({ startTime: time }),

  markAllAgentsComplete: () => set((state) => ({
    agentStatus: Object.fromEntries(
      Object.keys(state.agentStatus).map((a) => [a, 'completed' as const])
    ),
  })),

  setError: (error) => set({ error, completed: true }),

  reset: () => set(initialState),
}))