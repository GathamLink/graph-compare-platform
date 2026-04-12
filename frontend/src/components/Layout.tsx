import { Link, useLocation } from 'react-router-dom'
import { GitCompare } from 'lucide-react'

export default function Layout({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  const isCompare = location.pathname.includes('/compare')

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 顶部导航 */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 h-14 flex items-center gap-3">
          <Link to="/tasks" className="flex items-center gap-2 text-primary font-semibold text-lg hover:opacity-80 transition-opacity">
            <GitCompare className="w-5 h-5" />
            <span>图片对比平台</span>
          </Link>
          <div className="flex-1" />
        </div>
      </header>

      {/* 主内容区 */}
      <main className={isCompare ? '' : 'max-w-7xl mx-auto px-4 py-6'}>
        {children}
      </main>
    </div>
  )
}
