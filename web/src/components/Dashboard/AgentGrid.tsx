"use client"

import { CheckCircle, Loader2, XCircle, AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAnalysisStore } from '@/store/analysis'

const teams = [
  { name: 'Analyst Team', agents: ['Market Analyst', 'Sentiment Analyst', 'News Analyst', 'Fundamentals Analyst'] },
  { name: 'Research Team', agents: ['Bull Researcher', 'Bear Researcher', 'Research Manager'] },
  { name: 'Trading Team', agents: ['Trader'] },
  { name: 'Risk Management', agents: ['Aggressive Analyst', 'Neutral Analyst', 'Conservative Analyst'] },
  { name: 'Portfolio Management', agents: ['Portfolio Manager'] },
]

const statusIcons = {
  pending: AlertCircle,
  in_progress: Loader2,
  completed: CheckCircle,
  error: XCircle,
}

const statusColors = {
  pending: 'text-yellow-600 bg-yellow-100 dark:bg-yellow-900/30 dark:text-yellow-400',
  in_progress: 'text-blue-600 bg-blue-100 dark:bg-blue-900/30 dark:text-blue-400',
  completed: 'text-green-600 bg-green-100 dark:bg-green-900/30 dark:text-green-400',
  error: 'text-red-600 bg-red-100 dark:bg-red-900/30 dark:text-red-400',
}

export function AgentGrid() {
  const { agentStatus } = useAnalysisStore()

  return (
    <div className="space-y-4">
      {teams.map((team) => {
        const activeAgents = team.agents.filter(a => agentStatus[a] !== undefined)
        if (activeAgents.length === 0) return null

        return (
          <div key={team.name} className="space-y-2">
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">{team.name}</h3>
            <div className="space-y-1">
              {activeAgents.map((agent, i) => {
                const status = agentStatus[agent] || 'pending'
                const Icon = statusIcons[status]
                return (
                  <div key={agent} className="flex items-center gap-3 p-2 rounded-lg hover:bg-accent transition-colors">
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <Icon className={cn('h-4 w-4 animate-spin-slow', statusColors[status])} />
                      <span className="text-sm font-medium truncate">{agent}</span>
                    </div>
                    <span className={cn('text-xs font-medium px-2 py-0.5 rounded', statusColors[status])}>
                      {status.replace('_', ' ')}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}