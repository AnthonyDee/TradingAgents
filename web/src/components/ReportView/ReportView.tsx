"use client"

import { useEffect, useState } from 'react'
import { ArrowLeft, Download, FileText, BookOpen } from 'lucide-react'
import { Button } from '@/components/ui'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { api } from '@/lib/api'
import MarkdownRenderer from '@/lib/markdown'

interface ReportViewProps {
  runId: string
  onBack: () => void
}

export function ReportView({ runId, onBack }: ReportViewProps) {
  const [report, setReport] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchReport = async () => {
      try {
        const data = await api.getReport(runId)
        setReport(data)
      } catch (e: any) {
        setError(e.message)
      } finally {
        setLoading(false)
      }
    }
    fetchReport()
  }, [runId])

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center">
          <h2 className="text-xl font-bold text-red-600">Failed to load report</h2>
          <p className="text-muted-foreground mt-2">{error}</p>
          <Button onClick={onBack} className="mt-4">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back
          </Button>
        </div>
      </div>
    )
  }

  if (!report) {
    return <div className="flex h-full items-center justify-center">No report data</div>
  }

  const config = report.config

  const sections = [
    { key: 'analyst_reports', title: 'Analyst Team Reports', icon: '👥' },
    { key: 'research_team', title: 'Research Team Decision', icon: '🔬' },
    { key: 'trader_plan', title: 'Trading Team Plan', icon: '📈' },
    { key: 'risk_management', title: 'Risk Management Decision', icon: '⚖️' },
    { key: 'portfolio_manager_decision', title: 'Portfolio Manager Decision', icon: '🎯' },
  ].filter(s => report[s.key])

  const exportMarkdown = () => {
    let md = `# TradingAgents Analysis Report\n\n`
    md += `**Ticker:** ${config.ticker}\n`
    md += `**Date:** ${config.analysis_date}\n`
    md += `**Provider:** ${config.llm_provider}\n`
    md += `**Models:** Quick=${config.shallow_thinker}, Deep=${config.deep_thinker}\n\n`

    sections.forEach(s => {
      md += `## ${s.title}\n\n`
      const content = report[s.key]
      if (typeof content === 'object') {
        Object.entries(content).forEach(([k, v]) => {
          md += `### ${k}\n\n${v}\n\n`
        })
      } else {
        md += `${content}\n\n`
      }
    })

    const blob = new Blob([md], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `tradingagents-${config.ticker}-${config.analysis_date}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between p-4 border-b">
        <Button variant="ghost" onClick={onBack} className="gap-2">
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        <div className="flex-1 text-center">
          <h1 className="text-xl font-semibold">{report.config.ticker} - {report.config.analysis_date}</h1>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={exportMarkdown}>
            <Download className="mr-2 h-4 w-4" />
            Export MD
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl mx-auto space-y-6">
          {/* Config Summary */}
          <Card>
            <CardHeader>
              <CardTitle>Analysis Configuration</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div><span className="text-muted-foreground">Provider:</span> {config.llm_provider}</div>
                <div><span className="text-muted-foreground">Quick Model:</span> {config.shallow_thinker}</div>
                <div><span className="text-muted-foreground">Deep Model:</span> {config.deep_thinker}</div>
                <div><span className="text-muted-foreground">Depth:</span> {config.research_depth} rounds</div>
                <div><span className="text-muted-foreground">Analysts:</span> {config.analysts.join(', ')}</div>
                <div><span className="text-muted-foreground">Language:</span> {config.output_language}</div>
              </div>
            </CardContent>
          </Card>

          {/* Report Sections */}
          {sections.map((section) => (
            <Card key={section.key}>
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle className="flex items-center gap-2">
                  <span>{section.icon}</span>
                  {section.title}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="prose prose-sm dark:prose-invert max-w-none">
                  {(() => {
                    const content = report[section.key]
                    if (typeof content === 'object') {
                      return (
                        <>
                          {Object.entries(content).map(([k, v]) => (
                            <div key={k}>
                              <h3 className="text-lg font-semibold mt-4 mb-2">{k}</h3>
                              <MarkdownRenderer content={v as string} />
                            </div>
                          ))}
                        </>
                      )
                    }
                    return <MarkdownRenderer content={content as string} />
                  })()}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </div>
  )
}