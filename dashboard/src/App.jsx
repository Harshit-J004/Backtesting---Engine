import TradingBacktestAnalysis from './components/TradingBacktestAnalysis'
import ErrorBoundary from './components/ErrorBoundary'

function App() {
  return (
    <div className="min-h-screen bg-gray-100 p-4">
      <ErrorBoundary>
        <TradingBacktestAnalysis />
      </ErrorBoundary>
    </div>
  )
}

export default App
