"use client"

import { ScrollArea } from '@/components/ui/scroll-area'
import MarkdownRenderer from '@/lib/markdown'
import { useAnalysisStore } from '@/store/analysis'

export function ReportPane() {
  const { reportSections } = useAnalysisStore()

  // Find the most recent section with content
  let latestSection: string | null = null
  let latestContent: string | null = null

  const sectionOrder = [
    'market_report',
    'sentiment_report',
    'news_report',
    'fundamentals_report',
    'investment_plan',
    'trader_investment_plan',
    'final_trade_decision',
  ]

  for (const section of sectionOrder) {
    if (reportSections[section]) {
      latestSection = section
      latestContent = reportSections[section]
    }
  }

  const sectionTitles: Record<string, string> = {
    market_report: 'Market Analysis',
    sentiment_report: 'Social Sentiment',
    news_report: 'News Analysis',
    fundamentals_report: 'Fundamentals Analysis',
    investment_plan: 'Research Team Decision',
    trader_investment_plan: 'Trading Team Plan',
    final_trade_decision: 'Portfolio Management Decision',
  }

  if (!latestSection || !latestContent) {
    return (
      <ScrollArea className="h-[400px]">
        <div className="flex items-center justify-center h-full text-muted-foreground">
          Waiting for analysis report...
        </div>
      </ScrollArea>
    )
  }

  return (
    <ScrollArea className="h-[400px]">
      <div className="p-2">
        <h3 className="mb-3 text-sm font-medium text-muted-foreground">
          {sectionTitles[latestSection] || latestSection}
        </h3>
        <MarkdownRenderer content={latestContent} />
      </div>
    </ScrollArea>
  )
}