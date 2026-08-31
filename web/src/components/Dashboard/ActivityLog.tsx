"use client"

import { ScrollArea } from '@/components/ui/scroll-area'
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

export function ActivityLog() {
  const { toolCalls, messages } = useAnalysisStore()

  const allItems: ActivityItem[] = [
    ...toolCalls.map(t => ({ ...t, type: 'tool' as const, timestamp: t.timestamp })),
    ...messages.map(m => ({ ...m, type: 'message' as const, timestamp: m.timestamp })),
  ].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())

  if (allItems.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        Waiting for activity...
      </div>
    )
  }

  return (
    <ScrollArea className="h-[400px]">
      <div className="space-y-2 p-2">
        {allItems.slice(0, 50).map((item, index) => {
          const itemType: keyof typeof typeColors = isToolCall(item) ? 'tool' : (item.msg_type as keyof typeof typeColors) || 'message'
          return (
            <div key={index} className={cn('flex items-start gap-2 p-2 rounded text-sm', typeColors[itemType] || '')}>
              <span className="text-xs text-muted-foreground shrink-0 mr-2 font-mono">
                {new Date(item.timestamp).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
              </span>
              <span className="shrink-0">{typeIcons[itemType as keyof typeof typeIcons] || '•'}</span>
              <div className="flex-1 min-w-0 font-mono text-xs">
                {isToolCall(item) ? (
                  <>
                    <span className="font-medium">{item.name}</span>
                    <span className="text-muted-foreground ml-1">
                      {JSON.stringify(item.args).slice(0, 100)}
                    </span>
                  </>
                ) : (
                  <span className="truncate block">{item.content}</span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </ScrollArea>
  )
}