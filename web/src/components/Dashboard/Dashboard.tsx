"use client"

import { useEffect } from 'react'
import { RotateCcw, FileText, BarChart3 } from 'lucide-react'
import { Button } from '@/components/ui'
import { AgentGrid } from './AgentGrid'
import { ActivityLog } from './ActivityLog'
import { ReportPane } from './ReportPane'
import { FooterStats } from './FooterStats'
import { useAnalysisStore } from '@/store/analysis'
import { useAnalysisWS } from '@/lib/ws'
import { api } from '@/lib/api'
import MarkdownRenderer from '@/lib/markdown'

interface DashboardProps {
  runId: string
  onNew: () => void
}

export function Dashboard({ runId, onNew }: DashboardProps) {
  const { completed, error, runId: storeRunId } = useAnalysisStore()
  const { connected } = useAnalysisWS(runId)

  useEffect(() => {
    // Reset store for new run
    if (storeRunId !== runId) {
      useAnalysisStore.getState().reset()
    }
  }, [runId, storeRunId])

  const handleViewReport = async () => {
    const report = await api.getReport(runId)
    // Navigate to report view
    window.location.href = `/?run_id=${runId}&view=report`
  }

  const handleNewAnalysis = () => {
    onNew()
  }

  if (error) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between p-4 border-b">
          <h1 className="text-xl font-semibold">Analysis Failed</h1>
          <Button onClick={handleNewAnalysis} variant="outline">
            <RotateCcw className="mr-2 h-4 w-4" />
            New Analysis
          </Button>
        </div>
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="max-w-md text-center">
            <div className="text-red-600 text-6xl mb-4">⚠️</div>
            <h2 className="text-2xl font-bold mb-2">Analysis Failed</h2>
            <p className="text-muted-foreground mb-6">{error}</p>
            <Button onClick={handleNewAnalysis} className="w-full">
              <RotateCcw className="mr-2 h-4 w-4" />
              Start New Analysis
            </Button>
          </div>
        </div>
      </div>
    )
  }

  if (completed) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between p-4 border-b">
          <h1 className="text-xl font-semibold">Analysis Complete</h1>
          <div className="flex gap-2">
            <Button variant="outline" onClick={handleNewAnalysis}>
              <RotateCcw className="mr-2 h-4 w-4" />
              New Analysis
            </Button>
            <Button onClick={handleViewReport}>
              <FileText className="mr-2 h-4 w-4" />
              View Full Report
            </Button>
          </div>
        </div>
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex-1 grid lg:grid-cols-[60%_40%] overflow-hidden">
            <div className="flex flex-col border-r">
              <div className="p-4 border-b">
                <h2 className="font-semibold">Agent Progress</h2>
              </div>
              <div className="flex-1 overflow-y-auto p-4">
                <AgentGrid />
              </div>
            </div>
            <div className="flex flex-col">
              <div className="p-4 border-b">
                <h2 className="font-semibold">Activity Log</h2>
              </div>
              <div className="flex-1 overflow-hidden">
                <ActivityLog />
              </div>
            </div>
          </div>
          <div className="border-t p-4 bg-card">
            <h3 className="font-medium mb-3">Final Report Preview</h3>
            <div className="max-h-64 overflow-y-auto">
              <ReportPane />
            </div>
          </div>
          <FooterStats />
        </div>
      </div>
    )
  }

  // Running state
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between p-4 border-b">
        <h1 className="text-xl font-semibold">Live Analysis</h1>
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${connected ? 'bg-green-500' : 'bg-yellow-500'}`} />
          <span className="text-sm text-muted-foreground">
            {connected ? 'Connected' : 'Connecting...'}
          </span>
        </div>
      </div>
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 grid lg:grid-cols-[60%_40%] overflow-hidden">
          <div className="flex flex-col border-r">
            <div className="p-4 border-b">
              <h2 className="font-semibold">Agent Progress</h2>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              <AgentGrid />
            </div>
          </div>
          <div className="flex flex-col">
            <div className="p-4 border-b">
              <h2 className="font-semibold">Activity Log</h2>
            </div>
            <div className="flex-1 overflow-hidden">
              <ActivityLog />
            </div>
          </div>
        </div>
        <div className="border-t p-4 bg-card">
          <h3 className="font-medium mb-3">Current Report</h3>
          <div className="max-h-64 overflow-y-auto">
            <ReportPane />
          </div>
        </div>
        <FooterStats />
      </div>
    </div>
  )
}