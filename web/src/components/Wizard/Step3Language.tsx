"use client"

import { useState } from 'react'
import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Label } from '@/components/ui'
import { useWizardStore } from '@/store/wizard'

const languages = [
  { label: 'English', value: 'English' },
  { label: 'Chinese (中文)', value: 'Chinese' },
  { label: 'Japanese (日本語)', value: 'Japanese' },
  { label: 'Korean (한국어)', value: 'Korean' },
  { label: 'Hindi (हिन्दी)', value: 'Hindi' },
  { label: 'Spanish (Español)', value: 'Spanish' },
  { label: 'Portuguese (Português)', value: 'Portuguese' },
  { label: 'French (Français)', value: 'French' },
  { label: 'German (Deutsch)', value: 'German' },
  { label: 'Arabic (العربية)', value: 'Arabic' },
  { label: 'Russian (Русский)', value: 'Russian' },
  { label: 'Custom...', value: 'custom' },
]

export function Step3Language({ onNext }: { onNext: () => void }) {
  const { outputLanguage, setOutputLanguage } = useWizardStore()
  const [customLang, setCustomLang] = useState('')

  const handleChange = (value: string) => {
    if (value === 'custom') {
      // Will show custom input
    } else {
      setOutputLanguage(value)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <Label>Output Language</Label>
        <Select value={outputLanguage} onValueChange={handleChange}>
          <SelectTrigger>
            <SelectValue placeholder="Select language" />
          </SelectTrigger>
          <SelectContent>
            {languages.map((lang) => (
              <SelectItem key={lang.value} value={lang.value}>
                {lang.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {outputLanguage === 'custom' && (
          <input
            type="text"
            value={customLang}
            onChange={(e) => setCustomLang(e.target.value)}
            onBlur={() => customLang && (setOutputLanguage(customLang), setCustomLang(''))}
            className="mt-2 w-full"
            placeholder="Enter language name (e.g., Turkish, Vietnamese)"
            autoFocus
          />
        )}
      </div>

      <Button onClick={onNext} className="w-full">
        Continue
      </Button>
    </div>
  )
}