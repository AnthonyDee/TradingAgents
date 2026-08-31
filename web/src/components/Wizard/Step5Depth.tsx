"use client"

import { Button, RadioGroup, RadioGroupItem, Label } from '@/components/ui'
import { useWizardStore } from '@/store/wizard'

const depths = [
  { label: 'Shallow', value: 1, description: 'Quick research, few debate rounds' },
  { label: 'Medium', value: 3, description: 'Balanced research, moderate debate rounds' },
  { label: 'Deep', value: 5, description: 'Comprehensive research, in-depth debate rounds' },
]

export function Step5Depth({ onNext }: { onNext: () => void }) {
  const { researchDepth, setResearchDepth } = useWizardStore()

  return (
    <div className="space-y-6">
      <div>
        <Label className="block mb-3">Research Depth</Label>
        <RadioGroup value={researchDepth} onValueChange={setResearchDepth}>
          <div className="space-y-3">
            {depths.map((depth) => (
              <label key={depth.value} className="flex items-start gap-3 p-4 border rounded-lg hover:bg-accent cursor-pointer transition-colors">
                <RadioGroupItem value={depth.value} className="mt-1" />
                <div>
                  <span className="font-medium block">{depth.label}</span>
                  <span className="text-sm text-muted-foreground">{depth.description}</span>
                </div>
              </label>
            ))}
          </div>
        </RadioGroup>
      </div>

      <Button onClick={onNext} className="w-full">
        Continue
      </Button>
    </div>
  )
}