import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Search, GitCompare, Layers, Trash2, ChevronRight } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import Layout from '@/components/Layout'
import TaskStatusBadge from '@/components/TaskStatusBadge'
import { useTaskStore } from '@/store/taskStore'
import type { Task, DiffAlgo } from '@/types'
import { DIFF_ALGO_CONFIG } from '@/types'

const STATUS_TABS: { value: string; label: string }[] = [
  { value: 'all',       label: '全部' },
  { value: 'draft',     label: '草稿' },
  { value: 'active',    label: '进行中' },
  { value: 'completed', label: '已完成' },
]

export default function TaskListPage() {
  const navigate = useNavigate()
  const { tasks, total, loading, fetchTasks, createTask, deleteTask } = useTaskStore()

  const [search, setSearch]           = useState('')
  const [statusTab, setStatusTab]     = useState('all')
  const [createOpen, setCreateOpen]   = useState(false)
  const [newName, setNewName]         = useState('')
  const [newDesc, setNewDesc]         = useState('')
  const [newPairMode, setNewPairMode] = useState<'sequential' | 'prefix'>('sequential')
  const [newDiffAlgo, setNewDiffAlgo] = useState<DiffAlgo>('balanced')
  const [creating, setCreating]       = useState(false)
  const [deleteId, setDeleteId]       = useState<number | null>(null)

  const load = (s?: string, st?: string) => {
    fetchTasks({ search: s, status: st === 'all' ? undefined : st })
  }

  useEffect(() => { load(search, statusTab) }, [statusTab])

  const handleSearch = (v: string) => {
    setSearch(v)
    load(v, statusTab)
  }

  const handleCreate = async () => {
    if (!newName.trim()) { toast.error('请输入任务名称'); return }
    setCreating(true)
    try {
      const task = await createTask({
        name: newName.trim(),
        description: newDesc.trim() || undefined,
        pair_mode: newPairMode,
        diff_algo: newDiffAlgo,
      })
      toast.success('任务创建成功')
      setCreateOpen(false)
      setNewName('')
      setNewDesc('')
      setNewPairMode('sequential')
      setNewDiffAlgo('balanced')
      navigate(`/tasks/${task.id}/compare`)
    } catch (e: any) {
      toast.error(e?.message ?? '创建失败')
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async () => {
    if (!deleteId) return
    try {
      await deleteTask(deleteId)
      toast.success('任务已删除')
    } catch (e: any) {
      toast.error(e?.message ?? '删除失败')
    } finally {
      setDeleteId(null)
    }
  }

  return (
    <Layout>
      {/* 页头 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">对比任务</h1>
          <p className="text-sm text-gray-500 mt-0.5">共 {total} 个任务</p>
        </div>
        <Button onClick={() => setCreateOpen(true)} className="gap-2">
          <Plus className="w-4 h-4" />
          新建任务
        </Button>
      </div>

      {/* 搜索 & 筛选 */}
      <div className="flex items-center gap-4 mb-6">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <Input
            placeholder="搜索任务名称..."
            value={search}
            onChange={(e) => handleSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Tabs value={statusTab} onValueChange={(v) => setStatusTab(v)}>
          <TabsList>
            {STATUS_TABS.map((t) => (
              <TabsTrigger key={t.value} value={t.value}>{t.label}</TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      {/* 任务列表 */}
      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-44 rounded-xl" />
          ))}
        </div>
      ) : tasks.length === 0 ? (
        <EmptyState onNew={() => setCreateOpen(true)} />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {tasks.map((task) => (
            <TaskCard
              key={task.id}
              task={task}
              onOpen={() => navigate(`/tasks/${task.id}/compare`)}
              onCompare={() => navigate(`/tasks/${task.id}/compare`)}
              onDelete={() => setDeleteId(task.id)}
            />
          ))}
        </div>
      )}

      {/* 新建任务弹窗 */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>新建对比任务</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label>任务名称 <span className="text-red-500">*</span></Label>
              <Input
                placeholder="例如：登录页 UI 改版前后对比"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label>描述（可选）</Label>
              <Textarea
                placeholder="简要描述本次对比的目的..."
                value={newDesc}
                onChange={(e) => setNewDesc(e.target.value)}
                rows={3}
              />
            </div>
            {/* 配对模式 */}
            <div className="space-y-2">
              <Label>配对模式</Label>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setNewPairMode('sequential')}
                  className={`flex flex-col items-start gap-1 rounded-lg border px-3 py-2.5 text-left text-sm transition-colors ${
                    newPairMode === 'sequential'
                      ? 'border-primary bg-primary/5 text-primary'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <span className="font-medium">顺序配对</span>
                  <span className="text-xs text-gray-400">按上传顺序一一对应</span>
                </button>
                <button
                  type="button"
                  onClick={() => setNewPairMode('prefix')}
                  className={`flex flex-col items-start gap-1 rounded-lg border px-3 py-2.5 text-left text-sm transition-colors ${
                    newPairMode === 'prefix'
                      ? 'border-primary bg-primary/5 text-primary'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <span className="font-medium">前缀配对</span>
                  <span className="text-xs text-gray-400">按文件名前缀匹配<br/>如 home_A.png ↔ home_B.png</span>
                </button>
              </div>
            </div>
            {/* 对比策略 */}
            <div className="space-y-2">
              <Label>对比算法</Label>
              <div className="grid grid-cols-2 gap-2">
                {(Object.keys(DIFF_ALGO_CONFIG) as DiffAlgo[]).map((algo) => {
                  const cfg = DIFF_ALGO_CONFIG[algo]
                  const active = newDiffAlgo === algo
                  return (
                    <button
                      key={algo}
                      type="button"
                      onClick={() => setNewDiffAlgo(algo)}
                      className={`flex flex-col items-start gap-1 rounded-lg border px-3 py-2.5 text-left text-sm transition-colors ${
                        active
                          ? 'border-primary bg-primary/5 text-primary'
                          : 'border-gray-200 hover:border-gray-300'
                      }`}
                    >
                      <span className="font-medium">{cfg.icon} {cfg.label}</span>
                      <span className="text-xs text-gray-400 leading-tight">{cfg.desc}</span>
                    </button>
                  )
                })}
              </div>
              <p className="text-xs text-gray-400 pt-0.5">
                {DIFF_ALGO_CONFIG[newDiffAlgo].tip}
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>取消</Button>
            <Button onClick={handleCreate} disabled={creating}>
              {creating ? '创建中...' : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 删除确认 */}
      <AlertDialog open={!!deleteId} onOpenChange={(o) => !o && setDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除？</AlertDialogTitle>
            <AlertDialogDescription>
              删除后将同时删除该任务下所有图片及对比结果，操作不可恢复。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-red-500 hover:bg-red-600">
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Layout>
  )
}

/* ── TaskCard ─────────────────────────────────────────────────────────────── */
function TaskCard({
  task,
  onOpen,
  onCompare,
  onDelete,
}: {
  task: Task
  onOpen: () => void
  onCompare: () => void
  onDelete: () => void
}) {
  const date = new Date(task.created_at).toLocaleDateString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
  })

  return (
    <div
      className="group bg-white rounded-xl border border-gray-200 p-5 hover:border-primary/50 hover:shadow-sm transition-all cursor-pointer"
      onClick={onOpen}
    >
      <div className="flex items-start justify-between gap-2 mb-3">
        <h3 className="font-medium text-gray-900 line-clamp-2 flex-1">{task.name}</h3>
        <TaskStatusBadge status={task.status} />
      </div>

      {task.description && (
        <p className="text-sm text-gray-500 line-clamp-2 mb-3">{task.description}</p>
      )}

      <div className="flex items-center gap-2 text-xs text-gray-400 mb-4">
        <Layers className="w-3.5 h-3.5" />
        <span>{task.pair_count} 对图片</span>
        <span className="mx-1">·</span>
        <span>{date}</span>
      </div>

      <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
        <Button
          size="sm"
          variant="outline"
          className="flex-1 gap-1.5 text-xs"
          onClick={onCompare}
        >
          <GitCompare className="w-3.5 h-3.5" />
          开始对比
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="flex-1 gap-1.5 text-xs text-gray-600"
          onClick={onOpen}
        >
          管理图片
          <ChevronRight className="w-3.5 h-3.5" />
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="text-gray-400 hover:text-red-500 hover:bg-red-50 px-2"
          onClick={onDelete}
        >
          <Trash2 className="w-3.5 h-3.5" />
        </Button>
      </div>
    </div>
  )
}

/* ── EmptyState ───────────────────────────────────────────────────────────── */
function EmptyState({ onNew }: { onNew: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="w-16 h-16 rounded-2xl bg-cyan-50 flex items-center justify-center mb-4">
        <GitCompare className="w-8 h-8 text-primary" />
      </div>
      <h3 className="text-lg font-medium text-gray-900 mb-1">还没有对比任务</h3>
      <p className="text-sm text-gray-500 mb-6">创建一个任务，上传两组图片开始对比</p>
      <Button onClick={onNew} className="gap-2">
        <Plus className="w-4 h-4" />
        新建任务
      </Button>
    </div>
  )
}
