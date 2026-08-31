"use client"

import { useState, useEffect } from 'react'
import { Search, Loader2 } from 'lucide-react'
import { Button, Input, Label } from '@/components/ui'
import { useWizardStore } from '@/store/wizard'

interface SearchResult {
  symbol: string
  name: string
  type: string
}

export function Step1Ticker({ onNext }: { onNext: () => void }) {
  const { ticker, setTicker } = useWizardStore()
  const [suggestions, setSuggestions] = useState<SearchResult[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [searching, setSearching] = useState(false)

  const handleInputChange = async (value: string) => {
    setTicker(value)
    if (value.length < 1) {
      setSuggestions([])
      setShowSuggestions(false)
      return
    }
    setSearching(true)
    try {
      const res = await fetch(`/api/v1/search?q=${encodeURIComponent(value)}`)
      if (res.ok) {
        const data = await res.json()
        setSuggestions(data)
        setShowSuggestions(true)
      }
    } catch {
      setSuggestions([])
    } finally {
      setSearching(false)
    }
  }

  const handleSelect = (symbol: string) => {
    setTicker(symbol)
    setSuggestions([])
    setShowSuggestions(false)
  }

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest('.ticker-search')) {
        setShowSuggestions(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const isValid = ticker.length >= 1

  return (
    <div className="space-y-6">
      <div>
        <Label htmlFor="ticker">Ticker Symbol</Label>
        <div className="relative mt-1 ticker-search">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            id="ticker"
            value={ticker}
            onChange={(e) => handleInputChange(e.target.value)}
            placeholder="SPY, AAPL, 0700.HK, BTC-USD"
            className="pl-10"
            autoComplete="off"
            onFocus={() => ticker.length >= 1 && setShowSuggestions(true)}
          />
          {searching && <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 animate-spin text-muted-foreground" />}
        </div>
        {showSuggestions && suggestions.length > 0 && (
          <div className="absolute z-10 mt-1 w-full rounded-md border bg-popover p-1 shadow-lg max-h-60 overflow-auto">
            {suggestions.map((s) => (
              <button
                key={s.symbol}
                onClick={() => handleSelect(s.symbol)}
                className="flex w-full items-center gap-2 px-2 py-1.5 text-sm hover:bg-accent rounded"
              >
                <span className="font-mono font-medium">{s.symbol}</span>
                <span className="text-muted-foreground">{s.name}</span>
                <span className="text-xs text-muted-foreground">{s.type}</span>
              </button>
            ))}
          </div>
        )}
        <p className="mt-1 text-sm text-muted-foreground">
          Enter ticker with exchange suffix (e.g., 0700.HK, BTC-USD)
        </p>
      </div>

      <Button onClick={onNext} disabled={!isValid} className="w-full">
        Continue
      </Button>
    </div>
  )
}