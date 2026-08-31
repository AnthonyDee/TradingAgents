"use client"

import { useState, useEffect } from 'react'
import { Button, Input, Label, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui'
import { useWizardStore } from '@/store/wizard'
import { api } from '@/lib/api'

interface ModelOption {
  label: string
  value: string
}

export function Step7Models({ onNext }: { onNext: () => void }) {
  const { llmProvider, backendUrl, shallowThinker, deepThinker, setModels, setProvider } = useWizardStore()
  const [models, setModelsList] = useState<ModelOption[]>([])
  const [loading, setLoading] = useState(true)
  const [shallow, setShallow] = useState(shallowThinker)
  const [deep, setDeep] = useState(deepThinker)

  useEffect(() => {
    const fetchModels = async () => {
      if (!llmProvider) return
      try {
        const data = await api.getModels(llmProvider, backendUrl)
        setModelsList(data.models)
        // Set defaults if not set
        if (!shallow && data.models.length > 0) {
          setShallow(data.models[0].value)
        }
        if (!deep && data.models.length > 1) {
          setDeep(data.models[1].value)
        } else if (!deep && data.models.length > 0) {
          setDeep(data.models[0].value)
        }
      } catch {
        // fallback handled by empty models
      } finally {
        setLoading(false)
      }
    }
    fetchModels()
  }, [llmProvider, backendUrl])

  useEffect(() => {
    setModels(shallow, deep)
  }, [shallow, deep, setModels])

  if (loading) {
    return <div className="flex items-center justify-center h-64">Loading models...</div>
  }

  return (
    <div className="space-y-6">
      <div>
        <Label>Quick-Thinking Model</Label>
        <Select value={shallow} onValueChange={setShallow}>
          <SelectTrigger>
            <SelectValue placeholder="Select quick model" />
          </SelectTrigger>
          <SelectContent>
            {models.map((m) => (
              <SelectItem key={m.value} value={m.value}>
                {m.label}
              </SelectItem>
            ))}
            <SelectItem value="custom">Custom model ID...</SelectItem>
          </SelectContent>
        </Select>
        {shallow === 'custom' && (
          <Input
            placeholder="Enter custom model ID"
            value={shallow}
            onChange={(e) => setShallow(e.target.value)}
            className="mt-2 font-mono text-sm"
          />
        )}
      </div>

      <div>
        <Label>Deep-Thinking Model</Label>
        <Select value={deep} onValueChange={setDeep}>
          <SelectTrigger>
            <SelectValue placeholder="Select deep model" />
          </SelectTrigger>
          <SelectContent>
            {models.map((m) => (
              <SelectItem key={m.value} value={m.value}>
                {m.label}
              </SelectItem>
            ))}
            <SelectItem value="custom">Custom model ID...</SelectItem>
          </SelectContent>
        </Select>
        {deep === 'custom' && (
          <Input
            placeholder="Enter custom model ID"
            value={deep}
            onChange={(e) => setDeep(e.target.value)}
            className="mt-2 font-mono text-sm"
          />
        )}
      </div>

      <Button onClick={onNext} disabled={!shallow || !deep} className="w-full">
        Continue
      </Button>
    </div>
  )
}