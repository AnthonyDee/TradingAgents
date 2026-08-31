import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from './components/ui/toaster'
import { Wizard } from './components/Wizard/Wizard'
import { Dashboard } from './components/Dashboard/Dashboard'
import { ReportView } from './components/ReportView/ReportView'
import { History } from './components/History/History'
import { Layout } from './components/Layout'
import { useWizardStore } from './store/wizard'
import { useAnalysisStore } from './store/analysis'
import { api } from './lib/api'

function App() {
  const [view, setView] = useState<'wizard' | 'dashboard' | 'report' | 'history'>('wizard')
  const [runId, setRunId] = useState<string | null>(null)
  const { reset: resetWizard } = useWizardStore()
  const { reset: resetAnalysis } = useAnalysisStore()

  // Check for run_id in URL on load
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const urlRunId = params.get('run_id')
    if (urlRunId) {
      setRunId(urlRunId)
      const urlView = params.get('view')
      setView(urlView === 'report' ? 'report' : urlView === 'history' ? 'history' : 'dashboard')
    }
  }, [])

  const handleStartAnalysis = async (config: any) => {
    resetAnalysis()
    try {
      const { run_id } = await api.startAnalysis(config)
      setRunId(run_id)
      setView('dashboard')
      // Update URL without reload
      window.history.pushState({}, '', `/?run_id=${run_id}`)
    } catch (e: any) {
      alert(`Failed to start analysis: ${e.message}`)
    }
  }

  const handleNewAnalysis = () => {
    resetWizard()
    resetAnalysis()
    setRunId(null)
    setView('wizard')
    window.history.pushState({}, '', '/')
  }

  const handleViewReport = (id: string) => {
    setRunId(id)
    setView('report')
    window.history.pushState({}, '', `/?run_id=${id}`)
  }

  const handleViewHistory = () => {
    setView('history')
  }

  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route
            path="/"
            element={
              <>
                {view === 'wizard' && <Wizard onStart={handleStartAnalysis} />}
                {view === 'dashboard' && runId && <Dashboard runId={runId} onNew={handleNewAnalysis} onViewReport={handleViewReport} />}
                {view === 'report' && runId && <ReportView runId={runId} onBack={handleNewAnalysis} />}
                {view === 'history' && <History onViewReport={handleViewReport} onNew={handleNewAnalysis} />}
              </>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
      <Toaster />
    </BrowserRouter>
  )
}

export default App