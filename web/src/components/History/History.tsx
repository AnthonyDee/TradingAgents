"use client"

import { useEffect, useState } from 'react'
import { Search, Loader2, ArrowLeft, FileText } from 'lucide-react'
import { Button, Input } from '@/components/ui'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { api, type RunSummary } from '@/lib/api'

interface HistoryProps {
  onViewReport: (runId: string) => void
  onNew: () => void
}

export function History({ onViewReport, onNew }: HistoryProps) {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(0)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')

  const limit = 20

  useEffect(() => {
    const fetchRuns = async () => {
      setLoading(true)
      try {
        const data = await api.getHistory({ limit, offset: page * limit, status: statusFilter || undefined })
        setRuns(data.runs)
        setTotal(data.total)
      } catch (e: any) {
        console.error(e)
      } finally {
        setLoading(false)
      }
    }
    fetchRuns()
  }, [page, statusFilter])

  const statusColors = {
    completed: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
    running: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
    pending: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400',
    failed: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
  }

  const renderContent = () => {
    if (loading) {
      return (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      )
    }
    if (runs.length === 0) {
      return (
        <div className="flex items-center justify-center h-64 text-muted-foreground">
          No analyses found
        </div>
      )
    }
    return (
      <div className="space-y-3">
        {runs.map((run) => (
          <Card key={run.id} className="hover:shadow-md transition-shadow cursor-pointer"
            onClick={() => onViewReport(run.id)}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="font-mono text-lg font-semibold">{run.ticker}</div>
                  <Badge variant="secondary">{run.analysis_date}</Badge>
                  <Badge className={statusColors[run.status as keyof typeof statusColors] || 'bg-gray-100 text-gray-800'}
                    variant="outline">
                    {run.status}
                  </Badge>
                </div>
                <div className="flex items-center gap-4 text-sm text-muted-foreground">
                  <span>{new Date(run.created_at).toLocaleString()}</span>
                  {run.completed_at && (
                    <span> · Completed: {new Date(run.completed_at).toLocaleString()}</span>
                  )}
                  {run.error_message && (
                    <span className="text-red-600">Error: {run.error_message}</span>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    )
  }

  const renderPagination = () => {
    if (total <= limit) return null
    return (
      <div className="mt-6 flex items-center justify-center gap-2">
        <Button variant="outline" size="sm" onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}>
          Previous
        </Button>
        <span className="px-4 text-sm text-muted-foreground">
          Page {page + 1} of {Math.ceil(total / limit)}
        </span>
        <Button variant="outline" size="sm" onClick={() => setPage(p => p + 1)} disabled={(page + 1) * limit >= total}>
          Next
        </Button>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between p-4 border-b">
        <div className="flex items-center gap-4">
          <Button variant="ghost" onClick={onNew} className="gap-2">
            <ArrowLeft className="h-4 w-4" />
            New Analysis
          </Button>
          <h1 className="text-xl font-semibold">Analysis History</h1>
        </div>
        <div className="flex items-center gap-2">
          <Input
            placeholder="Search ticker..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-64"
          />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="h-10 px-3 rounded-md border border-input bg-background text-sm"
          >
            <option value="">All Status</option>
            <option value="completed">Completed</option>
            <option value="running">Running</option>
            <option value="pending">Pending</option>
            <option value="failed">Failed</option>
          </select>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {renderContent()}
        {renderPagination()}
      </div>
    </div>
  )
}