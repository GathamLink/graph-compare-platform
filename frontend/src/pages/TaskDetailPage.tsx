import { useEffect, useRef, useState, useCallback, memo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft, GitCompare, Upload, Trash2, Plus, GripVertical,
  AlertCircle, Loader2, FolderOpen, ChevronDown, ChevronUp,
  Settings, RefreshCw,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  DndContext, closestCenter, KeyboardSensor, PointerSensor,
  useSensor, useSensors,
} from '@dnd-kit/core'
import type { DragEndEvent } from '@dnd-kit/core'
import {
  SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy,
  useSortable, arrayMove,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import Layout from '@/components/Layout'
import TaskStatusBadge from '@/components/TaskStatusBadge'
import { useTaskStore } from '@/store/taskStore'
import { imageApi } from '@/api/imageApi'
import { diffApi } from '@/api/diffApi'
import { taskApi } from '@/api/taskApi'
import type { ImageBrief, DiffStatusResponse, DiffAlgo } from '@/types'
import { DIFF_ALGO_CONFIG } from '@/types'

const ACCEPT = 'image/jpeg,image/png,image/webp,image/gif'
// 配对预览默认展示行数，超过后折叠
const PAIR_PREVIEW_LIMIT = 12

export default function TaskDetailPage() {
  const { id } = useParams<{ id: string }>()
  const taskId = Number(id)
  const navigate = useNavigate()
  const { currentTask, taskLoading, fetchTask } = useTaskStore()

  // ── diff 进度：用独立 ref 存，避免每次轮询都触发整页重渲染 ──────────────
  const [diffStatus, setDiffStatus]   = useState<DiffStatusResponse | null>(null)
  const diffStatusRef = useRef<DiffStatusResponse | null>(null)
  const setDiff = useCallback((s: DiffStatusResponse) => {
    diffStatusRef.current = s
    setDiffStatus(s)  // 仍需触发一次 UI 更新，但后续轮询通过 ref 判断是否有变化
  }, [])

  const [batchOpen, setBatchOpen]         = useState(false)
  const [settingsOpen, setSettingsOpen]   = useState(false)
  const [recomputing, setRecomputing]     = useState(false)
  const [pairsExpanded, setPairsExpanded] = useState(false)

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // ── 轮询控制 ─────────────────────────────────────────────────────────────
  const stopPoll = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
  }, [])

  const startPoll = useCallback(() => {
    if (timerRef.current) return
    timerRef.current = setInterval(async () => {
      try {
        const s = await diffApi.status(taskId)
        // 只有数据真正变化才调用 setState，减少不必要重渲染
        const prev = diffStatusRef.current
        if (!prev || prev.done !== s.done || prev.running !== s.running || prev.failed !== s.failed) {
          setDiff(s)
        }
        if (s.pending === 0 && s.running === 0) stopPoll()
      } catch { /* silent */ }
    }, 5000)
  }, [taskId, stopPoll, setDiff])

  // 重新触发对比（放在 stopPoll/startPoll 之后，避免 undefined 引用）
  const handleRecompute = useCallback(async () => {
    if (recomputing) return
    setRecomputing(true)
    try {
      await diffApi.compute(taskId)
      toast.success('已重新触发对比，正在后台计算…')
      stopPoll()
      setTimeout(() => {
        diffApi.status(taskId).then((s) => { setDiff(s); startPoll() }).catch(() => {})
      }, 500)
    } catch (e: any) {
      toast.error(e?.message ?? '触发失败')
    } finally {
      setRecomputing(false)
    }
  }, [taskId, recomputing, stopPoll, startPoll, setDiff])

  useEffect(() => { fetchTask(taskId) }, [taskId])

  useEffect(() => {
    if (currentTask?.id !== taskId) return
    stopPoll()
    diffApi.status(taskId).then((s) => {
      setDiff(s)
      if (s.pending > 0 || s.running > 0) startPoll()
    }).catch(() => {})
    return stopPoll
  }, [currentTask?.id])

  const refresh = useCallback(() => fetchTask(taskId), [taskId])

  if (taskLoading || !currentTask) {
    return (
      <Layout>
        <div className="space-y-4">
          <Skeleton className="h-8 w-48" />
          <div className="grid grid-cols-2 gap-6">
            <Skeleton className="h-80" />
            <Skeleton className="h-80" />
          </div>
        </div>
      </Layout>
    )
  }

  const groupA   = currentTask.group_a ?? []
  const groupB   = currentTask.group_b ?? []
  const pairCount = Math.max(groupA.length, groupB.length)
  const diffDone  = diffStatus?.done ?? 0
  const diffTotal = diffStatus?.total ?? pairCount
  const diffPct   = diffTotal > 0 ? Math.round((diffDone / diffTotal) * 100) : 0
  const isCalc    = !!diffStatus && (diffStatus.running > 0 || diffStatus.pending > 0)

  // 配对预览：折叠时只渲染前 N 行
  const visiblePairs = pairsExpanded
    ? pairCount
    : Math.min(pairCount, PAIR_PREVIEW_LIMIT)

  return (
    <Layout>
      {/* 顶部导航 */}
      <div className="flex items-center gap-3 mb-6">
        <Button variant="ghost" size="sm" className="gap-1.5 text-gray-600" onClick={() => navigate('/tasks')}>
          <ArrowLeft className="w-4 h-4" />返回
        </Button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-xl font-semibold text-gray-900 truncate">{currentTask.name}</h1>
            <TaskStatusBadge status={currentTask.status} />
            {/* 配对模式标签 */}
            <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${
              currentTask.pair_mode === 'prefix'
                ? 'bg-violet-100 text-violet-700'
                : 'bg-gray-100 text-gray-500'
            }`}>
              {currentTask.pair_mode === 'prefix' ? '🔤 前缀配对' : '🔢 顺序配对'}
            </span>
          </div>
          {currentTask.description && (
            <p className="text-sm text-gray-500 mt-0.5 truncate">{currentTask.description}</p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="outline" size="sm" className="gap-1.5"
            onClick={handleRecompute} disabled={recomputing}
            title="清空已有对比结果，重新计算所有图片对"
          >
            {recomputing
              ? <Loader2 className="w-4 h-4 animate-spin" />
              : <RefreshCw className="w-4 h-4" />}
            重新对比
          </Button>
          <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setBatchOpen(true)}>
            <Plus className="w-4 h-4" />批量追加
          </Button>
          <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setSettingsOpen(true)}>
            <Settings className="w-4 h-4" />设置
          </Button>
          <Button
            size="sm" className="gap-1.5"
            disabled={pairCount === 0}
            onClick={() => navigate(`/tasks/${taskId}/compare`)}
          >
            <GitCompare className="w-4 h-4" />开始对比
          </Button>
        </div>
      </div>

      {/* 差异计算进度 */}
      {diffTotal > 0 && (
        <DiffProgressBar
          done={diffDone} total={diffTotal} pct={diffPct}
          isCalc={isCalc} status={diffStatus}
        />
      )}

      {/* 双组图片面板 */}
      <div className="grid grid-cols-2 gap-6">
        <ImageGroup taskId={taskId} group="A" label="图片组 A（原图）"   images={groupA} onRefresh={refresh} onStartPoll={startPoll} />
        <ImageGroup taskId={taskId} group="B" label="图片组 B（对比图）" images={groupB} onRefresh={refresh} onStartPoll={startPoll} />
      </div>

      {/* 配对预览 */}
      {pairCount > 0 && (
        <div className="mt-6">
          <div className="flex items-center gap-2 mb-3">
            <h2 className="text-sm font-medium text-gray-700">
              配对预览（共 {pairCount} 对）
            </h2>
            {currentTask.pair_mode === 'prefix' && (
              <span className="text-xs text-violet-600 bg-violet-50 px-2 py-0.5 rounded-full">
                按文件名前缀自动匹配
              </span>
            )}
          </div>
          <div className="space-y-2">
            {Array.from({ length: visiblePairs }).map((_, i) => (
              <PairRow
                key={i}
                index={i}
                imageA={groupA[i]}
                imageB={groupB[i]}
                onClick={() => navigate(`/tasks/${taskId}/compare/${i}`)}
              />
            ))}
          </div>

          {/* 折叠/展开按钮 */}
          {pairCount > PAIR_PREVIEW_LIMIT && (
            <button
              className="mt-3 w-full flex items-center justify-center gap-1.5 text-xs text-gray-400 hover:text-primary transition-colors py-2 border border-dashed border-gray-200 rounded-lg hover:border-primary/40"
              onClick={() => setPairsExpanded(v => !v)}
            >
              {pairsExpanded
                ? <><ChevronUp className="w-3.5 h-3.5" /> 收起（共 {pairCount} 对）</>
                : <><ChevronDown className="w-3.5 h-3.5" /> 展开剩余 {pairCount - PAIR_PREVIEW_LIMIT} 对</>
              }
            </button>
          )}
        </div>
      )}

      {/* 批量追加弹窗 */}
      <BatchAppendModal
        open={batchOpen} taskId={taskId}
        onClose={() => setBatchOpen(false)}
        onSuccess={() => { refresh(); startPoll() }}
      />

      {/* 任务设置弹窗 */}
      <TaskSettingsModal
        open={settingsOpen}
        task={currentTask}
        onClose={() => setSettingsOpen(false)}
        onSuccess={() => { refresh(); toast.success('任务设置已更新') }}
      />
    </Layout>
  )
}

/* ── 差异进度条（独立组件，state 变化只重渲染此处）────────────────────────── */
const DiffProgressBar = memo(({ done, total, pct, isCalc, status }: {
  done: number; total: number; pct: number; isCalc: boolean; status: DiffStatusResponse | null
}) => (
  <div className="mb-6 bg-white rounded-xl border border-gray-200 p-4">
    <div className="flex items-center justify-between mb-2">
      <span className="text-sm font-medium text-gray-700 flex items-center gap-1.5">
        {isCalc && <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />}
        差异计算进度
      </span>
      <span className="text-sm text-gray-500">{done} / {total}</span>
    </div>
    <Progress value={pct} className="h-2" />
    {status && (
      <div className="flex items-center gap-4 mt-2 text-xs text-gray-400">
        <span className="text-green-600">✓ 已完成 {status.done}</span>
        {status.running > 0 && <span className="text-cyan-600">⟳ 计算中 {status.running}</span>}
        {status.pending > 0 && <span>待计算 {status.pending}</span>}
        {status.failed  > 0 && <span className="text-red-500">✘ 失败 {status.failed}</span>}
      </div>
    )}
  </div>
))

/* ── 配对行（memo：props 不变时不重渲染）────────────────────────────────── */
const PairRow = memo(({ index, imageA, imageB, onClick }: {
  index: number; imageA?: ImageBrief; imageB?: ImageBrief; onClick: () => void
}) => (
  <div
    className="flex items-center gap-3 bg-white rounded-lg border border-gray-200 px-4 py-2 hover:border-primary/40 cursor-pointer transition-colors"
    onClick={onClick}
  >
    <span className="text-xs text-gray-400 w-8 shrink-0">#{index + 1}</span>
    <PairThumb image={imageA} label="A" />
    <span className="text-gray-300">↔</span>
    <PairThumb image={imageB} label="B" />
    <div className="flex-1" />
    <GitCompare className="w-3.5 h-3.5 text-gray-400" />
  </div>
))

/* ── 图片组组件 ─────────────────────────────────────────────────────────── */
function ImageGroup({
  taskId, group, label, images, onRefresh, onStartPoll,
}: {
  taskId: number; group: 'A' | 'B'; label: string
  images: ImageBrief[]; onRefresh: () => void; onStartPoll: () => void
}) {
  const [draggingOver, setDraggingOver] = useState(false)
  const [uploading, setUploading]       = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const [items, setItems]               = useState<ImageBrief[]>(images)

  useEffect(() => { setItems(images) }, [images])

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const uploadFiles = async (files: File[]) => {
    if (!files.length) return
    setUploading(true)
    try {
      await imageApi.upload(taskId, group, files)
      toast.success(`已上传 ${files.length} 张图片到组 ${group}`)
      onRefresh(); onStartPoll()
    } catch (e: any) {
      toast.error(e?.message ?? '上传失败')
    } finally { setUploading(false) }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDraggingOver(false)
    uploadFiles(Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/')))
  }

  const handleReorder = async (e: DragEndEvent) => {
    const { active, over } = e
    if (!over || active.id === over.id) return
    const oldIdx = items.findIndex(i => i.image_id === active.id)
    const newIdx = items.findIndex(i => i.image_id === over.id)
    const newItems = arrayMove(items, oldIdx, newIdx)
    setItems(newItems)
    try {
      await imageApi.reorder(taskId, group, newItems.map(i => i.image_id))
      onRefresh(); onStartPoll()
    } catch { setItems(images) }
  }

  const handleDelete = async (imageId: number) => {
    try {
      await imageApi.delete(taskId, imageId)
      toast.success('图片已删除'); onRefresh()
    } catch (e: any) { toast.error(e?.message ?? '删除失败') }
  }

  const color = group === 'A'
    ? 'text-cyan-700 bg-cyan-50 border-cyan-200'
    : 'text-violet-700 bg-violet-50 border-violet-200'

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className={`flex items-center justify-between px-4 py-3 border-b ${color}`}>
        <span className="text-sm font-medium">{label}</span>
        <span className="text-xs opacity-70">{items.length} 张</span>
      </div>

      {/* 拖拽上传区 */}
      <div
        className={`m-3 border-2 border-dashed rounded-lg p-3 text-center transition-colors cursor-pointer ${
          draggingOver ? 'border-primary bg-primary/5' : 'border-gray-200 hover:border-primary/50'
        }`}
        onDragOver={(e) => { e.preventDefault(); setDraggingOver(true) }}
        onDragLeave={() => setDraggingOver(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
      >
        {uploading
          ? <div className="flex items-center justify-center gap-2 py-1 text-sm text-gray-500"><Loader2 className="w-4 h-4 animate-spin" />上传中...</div>
          : <div className="flex items-center justify-center gap-2 py-1 text-sm text-gray-500"><Upload className="w-4 h-4" />点击或拖拽图片到此处上传</div>
        }
        <input ref={inputRef} type="file" multiple accept={ACCEPT} className="hidden"
          onChange={(e) => uploadFiles(Array.from(e.target.files ?? []))} />
      </div>

      {/* 图片列表：固定高度 + 内部滚动，避免撑高整页 */}
      <div className="px-3 pb-3 max-h-64 overflow-y-auto">
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleReorder}>
          <SortableContext items={items.map(i => i.image_id)} strategy={verticalListSortingStrategy}>
            <div className="space-y-1.5">
              {items.map((img, idx) => (
                <SortableImageItem key={img.image_id} image={img} index={idx}
                  onDelete={() => handleDelete(img.image_id)} />
              ))}
            </div>
          </SortableContext>
        </DndContext>
        {items.length === 0 && (
          <div className="text-center py-6 text-sm text-gray-400">
            <FolderOpen className="w-8 h-8 mx-auto mb-2 opacity-40" />暂无图片
          </div>
        )}
      </div>
    </div>
  )
}

/* ── 可排序图片项 ────────────────────────────────────────────────────────── */
const SortableImageItem = memo(({ image, index, onDelete }: {
  image: ImageBrief; index: number; onDelete: () => void
}) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: image.image_id })
  const style = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.5 : 1 }

  return (
    <div ref={setNodeRef} style={style}
      className="flex items-center gap-2 bg-gray-50 rounded-lg px-2 py-1.5 group hover:bg-gray-100 transition-colors"
    >
      <button {...attributes} {...listeners} className="cursor-grab text-gray-300 hover:text-gray-500 shrink-0">
        <GripVertical className="w-4 h-4" />
      </button>
      <span className="text-xs text-gray-400 w-5 shrink-0">{index + 1}</span>
      <img src={image.thumb_url ?? image.url} alt={image.original_name}
        className="w-8 h-8 object-cover rounded shrink-0 bg-gray-200" loading="lazy" />
      <span className="text-xs text-gray-600 truncate flex-1">{image.original_name}</span>
      <button className="text-gray-300 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100 shrink-0"
        onClick={onDelete}>
        <Trash2 className="w-3.5 h-3.5" />
      </button>
    </div>
  )
})

/* ── 配对缩略图 ─────────────────────────────────────────────────────────── */
function PairThumb({ image, label }: { image?: ImageBrief; label: string }) {
  if (!image) return (
    <div className="w-10 h-10 rounded bg-gray-100 flex items-center justify-center">
      <span className="text-xs text-gray-400">{label}</span>
    </div>
  )
  return <img src={image.thumb_url ?? image.url} alt={image.original_name}
    className="w-10 h-10 rounded object-cover bg-gray-100" loading="lazy" />
}

/* ── 批量追加弹窗（ZIP 导入模式）─────────────────────────────────────────── */
function BatchAppendModal({ open, taskId, onClose, onSuccess }: {
  open: boolean; taskId: number; onClose: () => void; onSuccess: () => void
}) {
  const [zipFile, setZipFile]       = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [dragging, setDragging]     = useState(false)
  const [showGuide, setShowGuide]   = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const reset = () => { setZipFile(null); setShowGuide(false) }
  const handleClose = () => { reset(); onClose() }

  const handleFile = (f: File) => {
    if (!f.name.toLowerCase().endsWith('.zip')) { toast.error('只接受 .zip 格式的压缩包'); return }
    setZipFile(f)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDragging(false)
    const f = e.dataTransfer.files[0]; if (f) handleFile(f)
  }

  const handleSubmit = async () => {
    if (!zipFile) { toast.error('请先选择 ZIP 文件'); return }
    setSubmitting(true)
    try {
      const res = await imageApi.importZip(taskId, zipFile)
      const total = res.appended.group_a.length + res.appended.group_b.length
      toast.success(`已导入 ${total} 张（A 组 ${res.appended.group_a.length}，B 组 ${res.appended.group_b.length}）`)
      reset(); onClose(); onSuccess()
    } catch (e: any) {
      const msg = (e as any)?.response?.data?.detail ?? (e as any)?.message ?? '导入失败'
      toast.error(msg)
    } finally { setSubmitting(false) }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && handleClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Upload className="w-4 h-4" />
            ZIP 压缩包批量导入
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-1">
          {/* 结构要求说明 */}
          <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 text-sm text-blue-800 space-y-1">
            <p className="font-medium">压缩包目录结构</p>
            <div className="font-mono text-xs text-blue-700 bg-blue-100 rounded px-3 py-2 mt-1 leading-relaxed select-all">
              <div>📦 upload.zip</div>
              <div className="ml-4">📁 root/  <span className="opacity-50">（名称随意）</span></div>
              <div className="ml-8">📁 原图/</div>
              <div className="ml-12 opacity-70">image_001.png</div>
              <div className="ml-12 opacity-70">image_002.png ...</div>
              <div className="ml-8">📁 对比图/</div>
              <div className="ml-12 opacity-70">image_001.png</div>
              <div className="ml-12 opacity-70">image_002.png ...</div>
            </div>
            <p className="text-xs text-blue-600 mt-1">
              根目录名称随意；两组按文件名字母顺序依次配对，数量可不相等
            </p>
          </div>

          {/* 折叠教程 */}
          <button
            type="button"
            onClick={() => setShowGuide(!showGuide)}
            className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 transition-colors w-full text-left"
          >
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            {showGuide ? '收起制作教程' : '如何制作符合结构的压缩包？'}
          </button>

          {showGuide && (
            <div className="bg-gray-50 border border-gray-200 rounded-lg px-4 py-3 text-xs text-gray-600 space-y-3">
              <div>
                <p className="font-semibold text-gray-700 mb-1">macOS / Linux（终端）</p>
                <div className="font-mono bg-white border border-gray-200 rounded px-3 py-2 leading-5 text-gray-600 select-all">
                  mkdir -p pack/root/原图 pack/root/对比图<br/>
                  cp 原图片/*.png pack/root/原图/<br/>
                  cp 对比图片/*.png pack/root/对比图/<br/>
                  cd pack && zip -r ../upload.zip root
                </div>
              </div>
              <div>
                <p className="font-semibold text-gray-700 mb-1">Windows（资源管理器）</p>
                <ol className="list-decimal list-inside space-y-0.5 text-gray-600">
                  <li>新建文件夹 <span className="font-mono bg-gray-100 px-1 rounded">原图</span> 和 <span className="font-mono bg-gray-100 px-1 rounded">对比图</span></li>
                  <li>将图片分别放入对应文件夹</li>
                  <li>同时选中两个文件夹 → 右键 → 压缩为 ZIP 文件</li>
                </ol>
              </div>
              <p className="text-amber-600 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                ⚠ 图片必须直接放在 <span className="font-mono">原图/</span> 或 <span className="font-mono">对比图/</span> 目录下，不支持嵌套子目录
              </p>
            </div>
          )}

          {/* 拖拽上传区 */}
          <div
            className={`border-2 border-dashed rounded-xl p-6 text-center transition-colors cursor-pointer ${
              dragging ? 'border-primary bg-primary/5'
              : zipFile ? 'border-green-400 bg-green-50'
              : 'border-gray-200 hover:border-primary/50'
            }`}
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
          >
            {zipFile ? (
              <div className="space-y-1">
                <div className="text-2xl">📦</div>
                <p className="text-sm font-medium text-green-700 truncate max-w-xs mx-auto">{zipFile.name}</p>
                <p className="text-xs text-gray-400">{(zipFile.size/1024/1024).toFixed(2)} MB · 点击重新选择</p>
              </div>
            ) : (
              <div className="space-y-2">
                <Upload className="w-8 h-8 mx-auto text-gray-300" />
                <p className="text-sm text-gray-500">点击或拖拽 ZIP 文件到此处</p>
                <p className="text-xs text-gray-400">仅支持 .zip 格式</p>
              </div>
            )}
            <input ref={inputRef} type="file" accept=".zip" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f) }} />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>取消</Button>
          <Button onClick={handleSubmit} disabled={!zipFile || submitting}>
            {submitting
              ? <><Loader2 className="w-4 h-4 animate-spin mr-1.5" />导入中…</>
              : '开始导入'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/* ── 任务设置弹窗 ───────────────────────────────────────────────────────── */
function TaskSettingsModal({ open, task, onClose, onSuccess }: {
  open: boolean
  task: { id: number; name: string; description?: string | null; pair_mode: string; diff_algo: string }
  onClose: () => void
  onSuccess: () => void
}) {
  const { updateTask } = useTaskStore()
  const [name, setName]               = useState(task.name)
  const [desc, setDesc]               = useState(task.description ?? '')
  const [pairMode, setPairMode]       = useState<string>(task.pair_mode)
  const [diffAlgo, setDiffAlgo]       = useState<DiffAlgo>(task.diff_algo as DiffAlgo)
  const [saving, setSaving]           = useState(false)

  // 弹窗打开时同步最新值
  useEffect(() => {
    if (open) {
      setName(task.name)
      setDesc(task.description ?? '')
      setPairMode(task.pair_mode)
      setDiffAlgo(task.diff_algo as DiffAlgo)
    }
  }, [open, task])

  const handleSave = async () => {
    if (!name.trim()) { toast.error('任务名称不能为空'); return }
    setSaving(true)
    try {
      await updateTask(task.id, {
        name: name.trim(),
        description: desc.trim() || undefined,
        pair_mode: pairMode as any,
        diff_algo: diffAlgo,
      })
      onClose()
      onSuccess()
    } catch (e: any) {
      toast.error(e?.message ?? '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const pairModes = [
    { value: 'sequential', label: '顺序配对', desc: '按上传顺序依次配对' },
    { value: 'prefix',     label: '前缀配对', desc: '按文件名前缀匹配（xxx_A.png ↔ xxx_B.png）' },
  ]

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Settings className="w-4 h-4" />
            任务设置
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-5 py-1">
          {/* 基本信息 */}
          <div className="space-y-3">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">基本信息</h3>
            <div className="space-y-1">
              <label className="text-sm font-medium text-gray-700">任务名称 *</label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="输入任务名称"
                maxLength={255}
              />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium text-gray-700">描述（可选）</label>
              <Textarea
                value={desc}
                onChange={(e) => setDesc(e.target.value)}
                placeholder="输入任务描述"
                rows={2}
                className="resize-none"
              />
            </div>
          </div>

          {/* 配对方式 */}
          <div className="space-y-2">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">配对方式</h3>
            <div className="grid grid-cols-2 gap-2">
              {pairModes.map((m) => (
                <button
                  key={m.value}
                  onClick={() => setPairMode(m.value)}
                  className={`text-left p-3 rounded-lg border-2 transition-all ${
                    pairMode === m.value
                      ? 'border-primary bg-primary/5'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className="font-medium text-sm text-gray-800">{m.label}</div>
                  <div className="text-xs text-gray-500 mt-0.5">{m.desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* 对比算法 */}
          <div className="space-y-2">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">对比算法</h3>
            <div className="space-y-2">
              {(Object.entries(DIFF_ALGO_CONFIG) as [DiffAlgo, typeof DIFF_ALGO_CONFIG[DiffAlgo]][]).map(([key, cfg]) => (
                <button
                  key={key}
                  onClick={() => setDiffAlgo(key)}
                  className={`w-full text-left p-3 rounded-lg border-2 transition-all ${
                    diffAlgo === key
                      ? 'border-primary bg-primary/5'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className="font-medium text-sm text-gray-800">{cfg.icon} {cfg.label}</div>
                  <div className="text-xs text-gray-500 mt-0.5">{cfg.desc}</div>
                  {diffAlgo === key && (
                    <div className="text-xs text-primary/70 mt-1">{cfg.tip}</div>
                  )}
                </button>
              ))}
            </div>
            <p className="text-xs text-gray-400">
              更改后需「重新对比」才会生效
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? <><Loader2 className="w-4 h-4 animate-spin mr-1" />保存中…</> : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
