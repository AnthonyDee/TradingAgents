"use client"

import { Button, Checkbox, Label } from '@/components/ui'
import { useWizardStore } from '@/store/wizard'

const analysts = [
  { key: 'market', label: 'Market Analyst', assetTypes: ['stock', 'crypto'] },
  { key: 'social', label: 'Sentiment Analyst', assetTypes: ['stock', 'crypto'] },
  { key: 'news', label: 'News Analyst', assetTypes: ['stock', 'crypto'] },
  { key: 'fundamentals', label: 'Fundamentals Analyst', assetTypes: ['stock'] },
]

const researchers = [
  { key: 'bull', label: 'Bull Researcher' },
  { key: 'bear', label: 'Bear Researcher' },
]

const riskDebators = [
  { key: 'aggressive', label: 'Aggressive Analyst' },
  { key: 'conservative', label: 'Conservative Analyst' },
  { key: 'neutral', label: 'Neutral Analyst' },
]

export function Step4Analysts({ onNext }: { onNext: () => void }) {
  const { analysts: selectedAnalysts, setAnalysts, researchers: selectedResearchers, setResearchers, risk: selectedRisk, setRisk, assetType } = useWizardStore()
  const availableAnalysts = analysts.filter(a => a.assetTypes.includes(assetType))

  const canContinue = selectedAnalysts.length > 0 && selectedResearchers.length > 0

  return (
    <div className="space-y-6">
      {/* Analyst Team */}
      <div>
        <Label className="block mb-3">Analyst Team</Label>
        <div className="space-y-2">
          {availableAnalysts.map((analyst) => (
            <label key={analyst.key} className="flex items-center gap-3 p-3 border rounded-lg hover:bg-accent cursor-pointer transition-colors">
              <Checkbox
                checked={selectedAnalysts.includes(analyst.key)}
                onCheckedChange={(checked: boolean) => {
                  const newSelection = checked
                    ? [...selectedAnalysts, analyst.key]
                    : selectedAnalysts.filter(a => a !== analyst.key)
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
      </div>

      {/* Research Team */}
      <div>
        <Label className="block mb-3">Research Team</Label>
        <div className="space-y-2">
          {researchers.map((researcher) => (
            <label key={researcher.key} className="flex items-center gap-3 p-3 border rounded-lg hover:bg-accent cursor-pointer transition-colors">
              <Checkbox
                checked={selectedResearchers.includes(researcher.key)}
                onCheckedChange={(checked: boolean) => {
                  const newSelection = checked
                    ? [...selectedResearchers, researcher.key]
                    : selectedResearchers.filter(r => r !== researcher.key)
                  setResearchers(newSelection)
                }}
              />
              <span className="font-medium">{researcher.label}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Risk Team */}
      <div>
        <Label className="block mb-3">Risk Team</Label>
        <div className="space-y-2">
          {riskDebators.map((debator) => (
            <label key={debator.key} className="flex items-center gap-3 p-3 border rounded-lg hover:bg-accent cursor-pointer transition-colors">
              <Checkbox
                checked={selectedRisk.includes(debator.key)}
                onCheckedChange={(checked: boolean) => {
                  const newSelection = checked
                    ? [...selectedRisk, debator.key]
                    : selectedRisk.filter(r => r !== debator.key)
                  setRisk(newSelection)
                }}
              />
              <span className="font-medium">{debator.label}</span>
            </label>
          ))}
        </div>
      </div>

      <p className="text-sm text-muted-foreground">
        At least one analyst and one researcher must be selected (risk debators are optional).
        Fundamentals Analyst not available for crypto.
      </p>

      <Button onClick={onNext} disabled={!canContinue} className="w-full">
        Continue
      </Button>
    </div>
  )
}
