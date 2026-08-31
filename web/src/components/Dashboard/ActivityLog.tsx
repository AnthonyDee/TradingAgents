"use client"

import { useState } from 'react'
import { Maximize2, Minimize2, WrapText } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useAnalysisStore } from '@/store/analysis'

const typeIcons = {
  tool: '🔧',
  message: '💬',
  user: '👤',
  agent: '🤖',
  data: '📊',
  control: '⚙️',
  system: '🖥️',
} as const

const typeColors = {
  tool: 'text-blue-600',
  message: 'text-green-600',
  user: 'text-purple-600',
  agent: 'text-orange-600',
  data: 'text-cyan-600',
  control: 'text-yellow-600',
  system: 'text-gray-600',
} as const

interface ToolCallItem {
  type: 'tool'
  name: string
  args: Record<string, any>
  timestamp: string
}

interface MessageItem {
  type: 'message'
  content: string
  timestamp: string
  msg_type?: string
}

type ActivityItem = ToolCallItem | MessageItem

function isToolCall(item: ActivityItem): item is ToolCallItem {
  return item.type === 'tool'
}

export function ActivityLog({
  expanded,
  onExpandedChange,
}: {
  expanded?: boolean
  onExpandedChange?: (v: boolean) => void
}) {
  const { toolCalls, messages } = useAnalysisStore()
  const [wrap, setWrap] = useState(false)
  const isExpanded = expanded ?? false
  const toggleExpanded = () => onExpandedChange?.(!isExpanded)

  const allItems: ActivityItem[] = [
    ...toolCalls.map(t => ({ ...t, type: 'tool' as const, timestamp: t.timestamp })),
    ...messages.map(m => ({ ...m, type: 'message' as const, timestamp: m.timestamp })),
  ].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())

  return (
    <div className="flex flex-col h-full min-h-[400px]">
      <div className="flex items-center justify-between px-3 py-1.5 border-b gap-2">
        <span className="text-sm font-medium text-muted-foreground">
          {allItems.length} events
        </span>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className={cn('h-7 w-7', wrap && 'bg-accent text-accent-foreground')}
            onClick={() => setWrap(w => !w)}
            title="Toggle text wrap"
            aria-pressed={wrap}
          >
            <WrapText className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={toggleExpanded}
            title={isExpanded ? 'Collapse log' : 'Expand log'}
          >
            {isExpanded ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </Button>
        </div>
      </div>

      {allItems.length === 0 ? (
        <div className="flex items-center justify-center flex-1 text-muted-foreground">
          Waiting for activity...
        </div>
      ) : (
        <ScrollArea className={cn('flex-1', !isExpanded && 'h-[400px]')}>
          <div className="space-y-1.5 p-2">
            {allItems.slice(0, 200).map((item, index) => {
              const itemType: keyof typeof typeColors = isToolCall(item) ? 'tool' : (item.msg_type as keyof typeof typeColors) || 'message'
              return (
                <div key={index} className={cn('flex items-start gap-2 p-1.5 rounded text-[11px]', typeColors[itemType] || '')}>
                  <span className="text-[10px] text-muted-foreground shrink-0 mr-1 font-mono">
                    {new Date(item.timestamp).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </span>
                  <span className="shrink-0">{typeIcons[itemType as keyof typeof typeIcons] || '•'}</span>
                  <div className={cn('flex-1 min-w-0 font-mono text-[11px]', wrap ? 'whitespace-pre-wrap break-words' : 'truncate')}>
                    {isToolCall(item) ? (
                      <>
                        <span className="font-medium">{item.name}</span>
                        <span className={cn('text-muted-foreground', wrap ? 'ml-1 block' : 'ml-1')}>
                          {JSON.stringify(item.args).slice(0, wrap ? 1000 : 100)}
                        </span>
                      </>
                    ) : (
                      <span className={cn(wrap ? 'block' : 'truncate block')}>{item.content}</span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </ScrollArea>
      )}
    </div>
  )
}
