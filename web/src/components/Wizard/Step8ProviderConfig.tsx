"use client"

import { Button, Label, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui'
import { useWizardStore } from '@/store/wizard'

const thinkingConfigs: Record<string, Array<{ label: string; value: string }>> = {
  google: [
    { label: 'Enable Thinking (recommended)', value: 'high' },
    { label: 'Minimal/Disable Thinking', value: 'minimal' },
  ],
  openai: [
    { label: 'High (More thorough)', value: 'high' },
    { label: 'Medium (Default)', value: 'medium' },
    { label: 'Low (Faster)', value: 'low' },
  ],
  anthropic: [
    { label: 'High (recommended)', value: 'high' },
    { label: 'Medium (balanced)', value: 'medium' },
    { label: 'Low (faster, cheaper)', value: 'low' },
  ],
}

const configLabels: Record<string, string> = {
  google_thinking_level: 'Gemini Thinking Mode',
  openai_reasoning_effort: 'OpenAI Reasoning Effort',
  anthropic_effort: 'Anthropic Effort Level',
}

export function Step8ProviderConfig({ onNext }: { onNext: () => void }) {
  const { llmProvider, googleThinkingLevel, openaiReasoningEffort, anthropicEffort, setProviderConfig } = useWizardStore()

  const configs = thinkingConfigs[llmProvider] ? [
    { key: `${llmProvider}_${llmProvider === 'google' ? 'thinking_level' : llmProvider === 'openai' ? 'reasoning_effort' : 'effort'}`, options: thinkingConfigs[llmProvider] }
  ] : []

  if (configs.length === 0) {
    return (
      <div className="space-y-6">
        <p className="text-center text-muted-foreground py-8">
          No additional configuration needed for {llmProvider}
        </p>
        <Button onClick={onNext} className="w-full">
          Start Analysis
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {configs.map(({ key, options }) => (
        <div key={key}>
          <Label>{configLabels[key]}</Label>
          <Select
            value={(key === 'google_thinking_level' ? googleThinkingLevel : key === 'openai_reasoning_effort' ? openaiReasoningEffort : anthropicEffort) || ''}
            onValueChange={(value: string) => setProviderConfig({ [key]: value })}
          >
            <SelectTrigger>
              <SelectValue placeholder="Select..." />
            </SelectTrigger>
            <SelectContent>
              {options.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ))}

      <Button onClick={onNext} className="w-full">
        Start Analysis
      </Button>
    </div>
  )
}