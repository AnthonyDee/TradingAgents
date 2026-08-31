"use client"

import { useState, useEffect } from 'react'
import { Button, Input, Label, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui'
import { useWizardStore } from '@/store/wizard'
import { api } from '@/lib/api'

interface ProviderOption {
  key: string
  label: string
  default_url?: string
  requires_region: boolean
  region_options?: Array<{ label: string; value: string }>
}

export function Step6Provider({ onNext }: { onNext: () => void }) {
  const { llmProvider, setProvider, backendUrl, assetType } = useWizardStore()
  const [providers, setProviders] = useState<ProviderOption[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedProvider, setSelectedProvider] = useState<ProviderOption | null>(null)
  const [customUrl, setCustomUrl] = useState('')

  useEffect(() => {
    const fetchProviders = async () => {
      try {
        const schema = await api.getConfigSchema()
        setProviders(schema.providers)
        const defaultProvider = schema.providers.find(p => p.key === 'openai_compatible') || schema.providers[0]
        setSelectedProvider(defaultProvider)
        if (defaultProvider.default_url) {
          setCustomUrl(defaultProvider.default_url)
        }
      } catch {
        // Fallback
      } finally {
        setLoading(false)
      }
    }
    fetchProviders()
  }, [])

  useEffect(() => {
    if (selectedProvider) {
      setProvider(selectedProvider.key, selectedProvider.default_url)
    }
  }, [selectedProvider, setProvider])

  const handleProviderChange = (key: string) => {
    const provider = providers.find(p => p.key === key)
    if (provider) {
      setSelectedProvider(provider)
      if (provider.default_url) {
        setCustomUrl(provider.default_url)
      }
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center h-64">Loading providers...</div>
  }

  return (
    <div className="space-y-6">
      <div>
        <Label>LLM Provider</Label>
        <Select value={selectedProvider?.key || ''} onValueChange={handleProviderChange}>
          <SelectTrigger>
            <SelectValue placeholder="Select provider" />
          </SelectTrigger>
          <SelectContent>
            {providers.map((p) => (
              <SelectItem key={p.key} value={p.key}>
                {p.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {selectedProvider && (
        <div>
          <Label>Backend URL</Label>
          <Input
            value={customUrl}
            onChange={(e) => setCustomUrl(e.target.value)}
            placeholder="http://e1.local:8000/v1"
            className="font-mono text-sm"
          />
          <p className="mt-1 text-sm text-muted-foreground">
            API endpoint for the selected provider
          </p>
        </div>
      )}

      <Button onClick={onNext} disabled={!selectedProvider || !customUrl} className="w-full">
        Continue
      </Button>
    </div>
  )
}