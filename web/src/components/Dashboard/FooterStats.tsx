"use client"

import { cn, formatTokens, formatDuration } from '@/lib/utils'
import { useAnalysisStore } from '@/store/analysis'

export function FooterStats() {
  const { agentStatus, reportSections, stats } = useAnalysisStore()

  const agentsCompleted = Object.values(agentStatus).filter(s => s === 'completed').length
  const agentsTotal = Object.keys(agentStatus).length

  const reportsCompleted = Object.values(reportSections).filter(s => s !== null).length
  const reportsTotal = Object.keys(reportSections).length

  return (
    <div className="flex flex-wrap items-center justify-center gap-4 px-4 py-2 text-sm text-muted-foreground border-t">
      <span className={cn('px-2 py-1 rounded bg-muted', agentsCompleted === agentsTotal ? 'text-green-600' : '')}>
        Agents: {agentsCompleted}/{agentsTotal}
      </span>
      <span className={cn('px-2 py-1 rounded bg-muted', reportsCompleted === reportsTotal ? 'text-green-600' : '')}>
        Reports: {reportsCompleted}/{reportsTotal}
      </span>
      <span className="px-2 py-1 rounded bg-muted">
        LLM: {stats.llm_calls}
      </span>
      <span className="px-2 py-1 rounded bg-muted">
        Tools: {stats.tool_calls}
      </span>
      <span className="px-2 py-1 rounded bg-muted">
        Tokens: {formatTokens(stats.tokens_in)}↑ {formatTokens(stats.tokens_out)}↓
      </span>
    </div>
  )
}