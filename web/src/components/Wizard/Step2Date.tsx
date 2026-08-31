"use client"

import { Button, Input, Label } from '@/components/ui'
import { useWizardStore } from '@/store/wizard'

export function Step2Date({ onNext }: { onNext: () => void }) {
  const { analysisDate, setAnalysisDate } = useWizardStore()
  const today = new Date().toISOString().split('T')[0]

  return (
    <div className="space-y-6">
      <div>
        <Label htmlFor="analysisDate">Analysis Date</Label>
        <Input
          id="analysisDate"
          type="date"
          value={analysisDate}
          onChange={(e) => setAnalysisDate(e.target.value)}
          max={today}
          className="mt-1"
        />
      </div>

      <Button onClick={onNext} className="w-full">
        Continue
      </Button>
    </div>
  )
}