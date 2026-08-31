import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface WizardState {
  // Step 1: Ticker
  ticker: string
  assetType: 'stock' | 'crypto'

  // Step 2: Date
  analysisDate: string

  // Step 3: Language
  outputLanguage: string

  // Step 4: Analysts
  analysts: string[]

  // Step 5: Depth
  researchDepth: number

  // Step 6: Provider
  llmProvider: string
  backendUrl: string

  // Step 7: Models
  shallowThinker: string
  deepThinker: string

  // Step 8: Provider config
  googleThinkingLevel?: string
  openaiReasoningEffort?: string
  anthropicEffort?: string

  // Actions
  setTicker: (ticker: string, assetType?: 'stock' | 'crypto') => void
  setAnalysisDate: (date: string) => void
  setOutputLanguage: (lang: string) => void
  setAnalysts: (analysts: string[]) => void
  setResearchDepth: (depth: number) => void
  setProvider: (provider: string, url?: string) => void
  setModels: (shallow: string, deep: string) => void
  setProviderConfig: (config: Partial<WizardState>) => void
  reset: () => void
  getConfig: () => any
}

const defaultState = {
  ticker: 'SPY',
  assetType: 'stock' as const,
  analysisDate: new Date().toISOString().split('T')[0],
  outputLanguage: 'English',
  analysts: ['market', 'social', 'news', 'fundamentals'],
  researchDepth: 1,
  llmProvider: 'openai_compatible',
  backendUrl: 'http://e1.local:8000/v1',
  shallowThinker: '',
  deepThinker: '',
  googleThinkingLevel: undefined,
  openaiReasoningEffort: undefined,
  anthropicEffort: undefined,
}

export const useWizardStore = create<WizardState>()(
  persist(
    (set, get) => ({
      ...defaultState,

      setTicker: (ticker, assetType) => {
        const type = assetType || (ticker.includes('-USD') || ticker.includes('-USDT') ? 'crypto' : 'stock')
        set({ ticker: ticker.toUpperCase(), assetType: type })
        // Auto-filter analysts for crypto
        if (type === 'crypto') {
          set({ analysts: get().analysts.filter(a => a !== 'fundamentals') })
        }
      },

      setAnalysisDate: (date) => set({ analysisDate: date }),

      setOutputLanguage: (lang) => set({ outputLanguage: lang }),

      setAnalysts: (analysts) => set({ analysts }),

      setResearchDepth: (depth) => set({ researchDepth: depth }),

      setProvider: (provider, url) => set({
        llmProvider: provider,
        backendUrl: url || get().backendUrl,
      }),

      setModels: (shallow, deep) => set({ shallowThinker: shallow, deepThinker: deep }),

      setProviderConfig: (config) => set((state) => ({ ...state, ...config })),

      reset: () => set(defaultState),

      getConfig: () => {
        const state = get()
        return {
          ticker: state.ticker,
          analysis_date: state.analysisDate,
          output_language: state.outputLanguage,
          analysts: state.analysts,
          research_depth: state.researchDepth,
          llm_provider: state.llmProvider,
          backend_url: state.backendUrl,
          shallow_thinker: state.shallowThinker,
          deep_thinker: state.deepThinker,
          google_thinking_level: state.googleThinkingLevel,
          openai_reasoning_effort: state.openaiReasoningEffort,
          anthropic_effort: state.anthropicEffort,
        }
      },
    }),
    {
      name: 'tradingagents-wizard',
      partialize: (state) => ({
        ticker: state.ticker,
        analysisDate: state.analysisDate,
        outputLanguage: state.outputLanguage,
        analysts: state.analysts,
        researchDepth: state.researchDepth,
        llmProvider: state.llmProvider,
        backendUrl: state.backendUrl,
        shallowThinker: state.shallowThinker,
        deepThinker: state.deepThinker,
        googleThinkingLevel: state.googleThinkingLevel,
        openaiReasoningEffort: state.openaiReasoningEffort,
        anthropicEffort: state.anthropicEffort,
      }),
    }
  )
)