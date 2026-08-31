"use client"

import { Button, Checkbox, Label } from '@/components/ui'
import { useWizardStore } from '@/store/wizard'

const analysts = [
  { key: 'market', label: 'Market Analyst', assetTypes: ['stock', 'crypto'] },
  { key: 'social', label: 'Sentiment Analyst', assetTypes: ['stock', 'crypto'] },
  { key: 'news', label: 'News Analyst', assetTypes: ['stock', 'crypto'] },
  { key: 'fundamentals', label: 'Fundamentals Analyst', assetTypes: ['stock'] },
]

export function Step4Analysts({ onNext }: { onNext: () => void }) {
  const { analysts: selected, setAnalysts, assetType } = useWizardStore()
  const availableAnalysts = analysts.filter(a => a.assetTypes.includes(assetType))

  return (
    <div className="space-y-6">
      <div>
        <Label className="block mb-3">Analyst Team</Label>
        <div className="space-y-2">
          {availableAnalysts.map((analyst) => (
            <label key={analyst.key} className="flex items-center gap-3 p-3 border rounded-lg hover:bg-accent cursor-pointer transition-colors">
              <Checkbox
                checked={selected.includes(analyst.key)}
                onCheckedChange={(checked: boolean) => {
                  const newSelection = checked
                    ? [...selected, analyst.key]
                    : selected.filter(a => a !== analyst.key)
                  setAnalysts(newSelection)
                }}
                disabled={!analyst.assetTypes.includes(assetType)}
              />
              <span className="font-medium">{analyst.label}</span>
              {!analyst.assetTypes.includes(assetType) && (
                <span className="ml-auto text-xs text-muted-foreground">Not available for {assetType}</span>
              )}
            </label>
          ))}
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          Select at least one analyst. Fundamentals Analyst not available for crypto.
        </p>
      </div>

      <Button onClick={onNext} disabled={selected.length === 0} className="w-full">
        Continue
      </Button>
    </div>
  )
}