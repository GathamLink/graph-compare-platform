import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import TaskListPage from '@/pages/TaskListPage'
import TaskDetailPage from '@/pages/TaskDetailPage'
import CompareListPage from '@/pages/CompareListPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/tasks" replace />} />
        <Route path="/tasks" element={<TaskListPage />} />
        <Route path="/tasks/:id" element={<TaskDetailPage />} />
        {/* /compare 进入列表页，弹窗由列表页内部管理 */}
        <Route path="/tasks/:id/compare" element={<CompareListPage />} />
        {/* 保留旧路由以兼容已有链接，自动重定向到列表页 */}
        <Route path="/tasks/:id/compare/:pairIndex" element={<CompareListPage />} />
      </Routes>
      <Toaster richColors position="top-right" />
    </BrowserRouter>
  )
}
