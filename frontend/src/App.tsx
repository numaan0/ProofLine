import { Header } from './components/layout/Header'
import { useRoute } from './lib/router'
import InspectionView from './pages/InspectionView'
import InspectionsList from './pages/InspectionsList'
import NewInspection from './pages/NewInspection'

function App() {
  const route = useRoute()
  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:px-3 focus:py-2 focus:bg-ink focus:text-white focus:rounded-md">
        Skip to content
      </a>
      <Header route={route} />
      <div id="main">
        {route.name === 'inspection' ? (
          <InspectionView key={route.id} id={route.id} taskId={route.taskId} />
        ) : route.name === 'list' ? (
          <InspectionsList />
        ) : (
          <NewInspection />
        )}
      </div>
    </div>
  )
}

export default App
