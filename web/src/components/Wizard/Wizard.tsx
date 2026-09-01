"use client"

import { useState } from 'react'
import { Check } from 'lucide-react'
import { Button, Card, CardContent } from '@/components/ui'
import { useWizardStore } from '@/store/wizard'
import { Step1Ticker } from './Step1Ticker'
import { Step2Date } from './Step2Date'
import { Step3Language } from './Step3Language'
import { Step4Analysts } from './Step4Analysts'
import { Step5Depth } from './Step5Depth'
import { Step6Provider } from './Step6Provider'
import { Step7Models } from './Step7Models'
import { Step8ProviderConfig } from './Step8ProviderConfig'

const steps = [
  { id: 1, title: 'Ticker', component: Step1Ticker },
  { id: 2, title: 'Date', component: Step2Date },
  { id: 3, title: 'Language', component: Step3Language },
  { id: 4, title: 'Agents Team', component: Step4Analysts },
  { id: 5, title: 'Depth', component: Step5Depth },
  { id: 6, title: 'Provider', component: Step6Provider },
  { id: 7, title: 'Models', component: Step7Models },
  { id: 8, title: 'Config', component: Step8ProviderConfig },
]

export function Wizard({ onStart }: { onStart: (config: any) => void }) {
  const [currentStep, setCurrentStep] = useState(1)
  const { getConfig, reset } = useWizardStore()

  const handleNext = () => {
    if (currentStep < steps.length) {
      setCurrentStep(currentStep + 1)
    } else {
      const config = getConfig()
      onStart(config)
    }
  }

  const handleBack = () => {
    if (currentStep > 1) {
      setCurrentStep(currentStep - 1)
    }
  }

  const currentStepData = steps[currentStep - 1]
  const CurrentComponent = currentStepData.component

  return (
    <div className="flex h-full flex-col lg:flex-row">
      {/* Progress Sidebar */}
      <div className="hidden lg:flex lg:w-64 flex-shrink-0 border-r bg-card">
        <div className="p-6 border-b">
          <h2 className="text-lg font-semibold mb-4">Configuration Steps</h2>
          <nav className="space-y-2">
            {steps.map((step, index) => (
              <button
                key={step.id}
                onClick={() => setCurrentStep(index + 1)}
                disabled={index + 1 > currentStep + 1}
                className={`w-full text-left p-3 rounded-lg transition-colors ${
                  index + 1 === currentStep
                    ? 'bg-primary text-primary-foreground'
                    : index + 1 < currentStep
                    ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                    : 'text-muted-foreground hover:bg-accent'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className={`flex items-center justify-center w-6 h-6 rounded-full text-xs font-medium ${
                    index + 1 < currentStep
                      ? 'bg-green-500 text-white'
                      : index + 1 === currentStep
                      ? 'bg-primary-foreground text-primary'
                      : 'bg-muted text-muted-foreground'
                  }`}>
                    {index + 1 < currentStep ? <Check className="h-4 w-4" /> : index + 1}
                  </span>
                  <span className="font-medium">{step.title}</span>
                </div>
              </button>
            ))}
          </nav>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 overflow-y-auto p-6 lg:p-8">
        <div className="max-w-2xl mx-auto">
          <div className="mb-8">
            <h1 className="text-3xl font-bold tracking-tight">TradingAgents Analysis</h1>
            <p className="mt-2 text-muted-foreground">
              Step {currentStep} of {steps.length}: {currentStepData.title}
            </p>
            <div className="mt-4 h-2 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full bg-primary transition-all duration-300"
                style={{ width: `${(currentStep / steps.length) * 100}%` }}
              />
            </div>
          </div>

          <Card>
            <CardContent className="p-6">
              <CurrentComponent onNext={handleNext} />
            </CardContent>
          </Card>

          <div className="mt-6 flex justify-between">
            <Button variant="outline" onClick={handleBack} disabled={currentStep === 1}>
              Back
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}