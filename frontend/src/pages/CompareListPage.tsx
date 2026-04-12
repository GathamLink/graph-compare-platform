import { toast } from 'sonner'
import { useEffect, useState, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft, RefreshCw, Search, ChevronDown, Loader2,
  CheckCircle2, XCircle, AlertCircle, Clock, GitCompare,
  Columns2, SlidersHorizontal, Eye, EyeOff, ZoomIn, ZoomOut,
  RotateCcw, AlertTriangle, X, Settings, Download,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Progress } from '@/components/ui/progress'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuCheckboxItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import Layout from '@/components/Layout'
import { useTaskStore } from '@/store/taskStore'
import { useCompareStore } from '@/store/compareStore'
import { diffApi } from '@/api/diffApi'
import type { DiffPairResponse, DiffStatusResponse } from '@/types'
import { DIFF_ALGO_CONFIG, type DiffAlgo } from '@/types'

// ─── 相似度类型 ───────────────────────────────────────────────────────────────
type SimilarityFilter = 'all' | 'similar' | 'different' | 'warning' | 'pending'

interface PairSummary {
  index: number
  imgAName?: string
  imgBName?: string
  imgAUrl?: string
  imgBUrl?: string
  diffUrl?: string
  score?: number
  isSimilar?: boolean | null
  status: string
  sizeWarning: boolean
}

function getPairCategory(p: PairSummary): SimilarityFilter {
  if (p.status === 'pending' || p.status === 'running') return 'pending'
  if (p.status === 'failed') return 'warning'
  if (p.sizeWarning) return 'warning'
  if (p.isSimilar === false) return 'different'
  if (p.isSimilar === true) return 'similar'
  return 'pending'
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────
export default function CompareListPage() {
  const { id } = useParams<{ id: string }>()
  const taskId = Number(id)
  const navigate = useNavigate()

  const { currentTask, fetchTask } = useTaskStore()
  const [diffStatus, setDiffStatus] = useState<DiffStatusResponse | null>(null)
  const [pairs, setPairs] = useState<PairSummary[]>([])
  const [loadingPairs, setLoadingPairs] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 筛选 & 搜索
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState<Set<SimilarityFilter>>(new Set(['all']))

  // 弹窗状态
  const [modalIndex, setModalIndex] = useState<number | null>(null)

  // 加载任务
  useEffect(() => {
    if (!currentTask || currentTask.id !== taskId) fetchTask(taskId)
  }, [taskId])

  // 加载所有配对摘要
  const loadAllPairs = useCallback(async () => {
    if (!currentTask) return
    const count = Math.max(currentTask.group_a.length, currentTask.group_b.length)
    if (count === 0) return
    setLoadingPairs(true)
    try {
      const results = await Promise.all(
        Array.from({ length: count }, (_, i) =>
          diffApi.getPair(taskId, i).catch(() => null)
        )
      )
      const summaries: PairSummary[] = results.map((d, i) => {
        const imgA = currentTask.group_a[i]
        const imgB = currentTask.group_b[i]
        if (!d) {
          return {
            index: i,
            imgAName: imgA?.original_name,
            imgBName: imgB?.original_name,
            imgAUrl: imgA?.thumb_url ?? imgA?.url,   // 列表用缩略图
            imgBUrl: imgB?.thumb_url ?? imgB?.url,   // 列表用缩略图
            status: 'pending',
            sizeWarning: false,
          }
        }
        return {
          index: i,
          imgAName: d.image_a?.original_name ?? imgA?.original_name,
          imgBName: d.image_b?.original_name ?? imgB?.original_name,
          imgAUrl: (d.image_a?.thumb_url ?? d.image_a?.url) ?? (imgA?.thumb_url ?? imgA?.url),
          imgBUrl: (d.image_b?.thumb_url ?? d.image_b?.url) ?? (imgB?.thumb_url ?? imgB?.url),
          diffUrl: d.diff_url ?? undefined,
          score: d.diff_score ?? undefined,
          isSimilar: d.is_similar,
          status: d.status,
          sizeWarning: d.size_warning,
        }
      })
      setPairs(summaries)
    } finally {
      setLoadingPairs(false)
    }
  }, [currentTask, taskId])

  useEffect(() => {
    if (currentTask) loadAllPairs()
  }, [currentTask?.id])

  // 轮询进度
  const stopPoll = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
  }, [])

  const startPoll = useCallback(() => {
    if (timerRef.current) return
    timerRef.current = setInterval(async () => {
      const s = await diffApi.status(taskId).catch(() => null)
      if (!s) return
      setDiffStatus(s)
      if (s.pending === 0 && s.running === 0) {
        stopPoll()
        loadAllPairs()  // 全部完成后刷新列表
      } else {
        loadAllPairs()  // 计算中也刷新（实时更新）
      }
    }, 5000)
  }, [taskId, stopPoll, loadAllPairs])

  useEffect(() => {
    if (!currentTask) return
    diffApi.status(taskId).then((s) => {
      setDiffStatus(s)
      if (s.pending > 0 || s.running > 0) startPoll()
    }).catch(() => {})
    return stopPoll
  }, [currentTask?.id])

  // ── 过滤逻辑 ──────────────────────────────────────────────────────────────
  const toggleFilter = (f: SimilarityFilter) => {
    setFilters(prev => {
      const next = new Set(prev)
      if (f === 'all') return new Set(['all'])
      next.delete('all')
      if (next.has(f)) { next.delete(f); if (next.size === 0) next.add('all') }
      else next.add(f)
      return next
    })
  }

  const handleExportReport = async () => {
    const url = diffApi.reportUrl(taskId)
    toast.loading('正在生成报告，请稍候…', { id: 'report' })
    try {
      const resp = await fetch(url)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const oversized = resp.headers.get('X-Oversized') === 'true'
      const blob = await resp.blob()
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `report_${currentTask?.name ?? taskId}.html`
      a.click()
      URL.revokeObjectURL(a.href)
      if (oversized) {
        toast.warning('报告图片总大小超过 50MB，已切换为 URL 加载模式，查看时需连接 MinIO 服务。', { id: 'report', duration: 6000 })
      } else {
        toast.success('报告已下载，可离线查看', { id: 'report' })
      }
    } catch (e: any) {
      toast.error('报告生成失败：' + (e?.message ?? '未知错误'), { id: 'report' })
    }
  }

  const filtered = pairs.filter(p => {    const cat = getPairCategory(p)
    const passFilter = filters.has('all') || filters.has(cat)
    const q = search.trim().toLowerCase()
    const passSearch = !q || (
      `#${p.index + 1}`.includes(q) ||
      (p.imgAName ?? '').toLowerCase().includes(q) ||
      (p.imgBName ?? '').toLowerCase().includes(q)
    )
    return passFilter && passSearch
  })

  // ── 进度统计 ──────────────────────────────────────────────────────────────
  const pairCount = currentTask
    ? Math.max(currentTask.group_a.length, currentTask.group_b.length)
    : 0
  const doneCount  = pairs.filter(p => p.status === 'done').length
  const progPct    = pairCount > 0 ? Math.round((doneCount / pairCount) * 100) : 0
  const isCalc     = diffStatus ? (diffStatus.running > 0 || diffStatus.pending > 0) : false

  if (!currentTask) {
    return (
      <Layout>
        <div className="space-y-4">
          <Skeleton className="h-8 w-64" />
          <div className="space-y-2">
            {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-16" />)}
          </div>
        </div>
      </Layout>
    )
  }

  return (
    <Layout>
      <div className="max-w-5xl mx-auto">
      {/* ── 顶部 ───────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 mb-5">
        {/* 返回 → 任务列表 */}
        <Button variant="ghost" size="sm" className="gap-1.5 text-gray-600"
          onClick={() => navigate('/tasks')}>
          <ArrowLeft className="w-4 h-4" />返回
        </Button>
        <div className="flex-1 min-w-0">
          <h1 className="text-lg font-semibold text-gray-900 truncate">{currentTask.name}</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            共 {pairCount} 对  ·  已完成 {doneCount}  ·  {
              DIFF_ALGO_CONFIG[currentTask.diff_algo as DiffAlgo]?.label ?? '均衡模式'
            }
          </p>
        </div>
        {isCalc && (
          <div className="flex items-center gap-1.5 text-xs text-cyan-600">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            计算中…
          </div>
        )}
        {/* 管理按钮 → 跳转任务详情页 */}
        <Button variant="outline" size="sm" className="gap-1.5 shrink-0"
          onClick={() => navigate(`/tasks/${taskId}`)}>
          <Settings className="w-4 h-4" />
          任务管理
        </Button>
        {/* 导出报告 */}
        <Button variant="outline" size="sm" className="gap-1.5 shrink-0"
          onClick={() => handleExportReport()}>
          <Download className="w-4 h-4" />
          导出报告
        </Button>
      </div>

      {/* ── 进度条（有计算任务时显示） ────────────────────────────────── */}
      {pairCount > 0 && (
        <div className="mb-5 bg-white rounded-xl border border-gray-200 px-4 py-3">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs text-gray-500">对比进度</span>
            <span className="text-xs font-medium text-gray-700">{doneCount} / {pairCount}</span>
          </div>
          <Progress value={progPct} className="h-1.5" />
        </div>
      )}

      {/* ── 搜索 & 筛选 ────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 mb-4">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索图片名称或编号…"
            className="pl-8 h-9 text-sm"
          />
        </div>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="gap-1.5 h-9">
              <span className="text-sm">
                {filters.has('all') ? '全部类型' : `已选 ${filters.size} 项`}
              </span>
              <ChevronDown className="w-3.5 h-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            {([
              ['all',       '全部'],
              ['similar',   '相同'],
              ['different', '差异'],
              ['warning',   '异常'],
              ['pending',   '待计算'],
            ] as [SimilarityFilter, string][]).map(([v, label]) => (
              <DropdownMenuCheckboxItem
                key={v}
                checked={filters.has(v)}
                onCheckedChange={() => toggleFilter(v)}
              >
                {label}
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        <span className="text-xs text-gray-400 ml-1">
          {filters.has('all') ? `${filtered.length} 对` : `${filtered.length} / ${pairs.length}`}
        </span>
      </div>

      {/* ── 配对列表 ────────────────────────────────────────────────────── */}
      {loadingPairs && pairs.length === 0 ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-20 rounded-xl" />)}
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <GitCompare className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm">没有符合条件的配对</p>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((p) => (
            <PairRow
              key={p.index}
              pair={p}
              onClick={() => setModalIndex(p.index)}
            />
          ))}
        </div>
      )}

      {/* ── 对比详情弹窗 ─────────────────────────────────────────────── */}
      {modalIndex !== null && (
        <CompareDetailModal
          taskId={taskId}
          taskName={currentTask.name}
          diffAlgo={currentTask.diff_algo}
          initialIndex={modalIndex}
          pairCount={pairCount}
          onClose={() => setModalIndex(null)}
        />
      )}
      </div>
    </Layout>
  )
}

// ─── 配对行 ────────────────────────────────────────────────────────────────
const PairRow = ({ pair, onClick }: { pair: PairSummary; onClick: () => void }) => {
  const cat = getPairCategory(pair)

  const badge = {
    similar:   { icon: <CheckCircle2 className="w-3.5 h-3.5" />, text: '相同', bg: 'bg-green-50 text-green-700 border-green-200' },
    different: { icon: <XCircle      className="w-3.5 h-3.5" />, text: '差异', bg: 'bg-red-50   text-red-700   border-red-200'   },
    warning:   { icon: <AlertCircle  className="w-3.5 h-3.5" />, text: '异常', bg: 'bg-amber-50 text-amber-700 border-amber-200' },
    pending:   { icon: <Clock        className="w-3.5 h-3.5" />, text: pair.status === 'running' ? '计算中…' : '待计算', bg: 'bg-gray-50  text-gray-500  border-gray-200'  },
    all:       { icon: null, text: '', bg: '' },
  }[cat]

  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-3 bg-white rounded-xl border border-gray-200 px-4 py-3 hover:border-primary/40 hover:shadow-sm transition-all text-left group"
    >
      {/* 状态徽章（最左侧，固定宽度对齐） */}
      <div className="w-20 shrink-0 flex justify-center">
        {badge.text ? (
          <div className={`flex items-center gap-1 px-2 py-1 rounded-lg border text-xs font-medium ${badge.bg}`}>
            {badge.icon}
            <span>{badge.text}</span>
          </div>
        ) : (
          <div className="w-20" />
        )}
      </div>

      {/* 编号 + 文件名（撑满中间，无左侧 A 图缩略图） */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-gray-400">#{pair.index + 1}</span>
          {pair.sizeWarning && (
            <span className="text-[10px] bg-amber-50 text-amber-600 border border-amber-200 rounded px-1">尺寸差异</span>
          )}
        </div>
        <p className="text-sm text-gray-700 truncate mt-0.5">{pair.imgAName ?? '—'}</p>
        <p className="text-xs text-gray-400 truncate">↔ {pair.imgBName ?? '—'}</p>
      </div>

      {/* B 图缩略图（右侧第一张） */}
      <div className="w-12 h-12 rounded-lg overflow-hidden bg-gray-100 shrink-0 border border-gray-200">
        {pair.imgBUrl
          ? <img src={pair.imgBUrl} alt="B" className="w-full h-full object-cover" loading="lazy" />
          : <div className="w-full h-full flex items-center justify-center text-xs text-gray-400">B</div>
        }
      </div>

      {/* 差异图预览（右侧第二张，hover 才完全显示） */}
      <div className="w-12 h-12 rounded-lg overflow-hidden bg-gray-100 shrink-0 border border-gray-200 opacity-50 group-hover:opacity-100 transition-opacity">
        {pair.diffUrl
          ? <img src={pair.diffUrl} alt="diff" className="w-full h-full object-cover" loading="lazy" />
          : <div className="w-full h-full flex items-center justify-center text-gray-300">
              <GitCompare className="w-4 h-4" />
            </div>
        }
      </div>

      <GitCompare className="w-4 h-4 text-gray-300 group-hover:text-primary transition-colors shrink-0" />
    </button>
  )
}

// ─── 对比详情弹窗 ──────────────────────────────────────────────────────────
function CompareDetailModal({ taskId, taskName, diffAlgo, initialIndex, pairCount, onClose }: {
  taskId: number
  taskName: string
  diffAlgo: string
  initialIndex: number
  pairCount: number
  onClose: () => void
}) {
  const {
    currentPairIndex, viewMode, showDiff, zoom,
    setCurrentPair, setViewMode, toggleDiff, setZoom,
    fetchPair, currentPairData, pairLoading,
  } = useCompareStore()

  const [localIdx, setLocalIdx] = useState(initialIndex)

  useEffect(() => {
    setCurrentPair(initialIndex)
    fetchPair(taskId, initialIndex)
  }, [])

  const goTo = (idx: number) => {
    if (idx < 0 || idx >= pairCount) return
    setLocalIdx(idx)
    setCurrentPair(idx)
    fetchPair(taskId, idx)
  }

  // 键盘导航（弹窗内）
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { onClose(); return }
      if (e.key === 'ArrowLeft')  goTo(localIdx - 1)
      if (e.key === 'ArrowRight') goTo(localIdx + 1)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [localIdx, pairCount])

  const pair = currentPairData

  return (
    <TooltipProvider>
      {/* 遮罩 */}
      <div
        className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex flex-col"
        onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
      >
        {/* 弹窗主体：全屏 */}
        <div className="flex flex-col h-full">
          {/* ── 顶部工具栏 ──────────────────────────────────────────────── */}
          <header className="h-14 bg-white border-b border-gray-200 flex items-center px-4 gap-3 shrink-0 z-10">
            <Button variant="ghost" size="sm" className="gap-1.5 text-gray-600 shrink-0" onClick={onClose}>
              <X className="w-4 h-4" />关闭
            </Button>
            <div className="h-5 w-px bg-gray-200" />
            <span className="text-sm font-medium text-gray-700 truncate max-w-[160px] hidden sm:block">{taskName}</span>
            <div className="h-5 w-px bg-gray-200 hidden sm:block" />
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="sm" className="px-2" disabled={localIdx === 0}
                onClick={() => goTo(localIdx - 1)}>
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15,18 9,12 15,6"/></svg>
              </Button>
              <span className="text-sm font-medium text-gray-700 min-w-[72px] text-center">
                {localIdx + 1} / {pairCount}
              </span>
              <Button variant="ghost" size="sm" className="px-2" disabled={localIdx >= pairCount - 1}
                onClick={() => goTo(localIdx + 1)}>
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9,18 15,12 9,6"/></svg>
              </Button>
            </div>
            <div className="flex-1" />

            {/* 视图模式 */}
            <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
              <Button variant={viewMode === 'side-by-side' ? 'default' : 'ghost'} size="sm"
                className="px-2.5 h-7" onClick={() => setViewMode('side-by-side')}>
                <Columns2 className="w-4 h-4" />
              </Button>
              <Button variant={viewMode === 'slider' ? 'default' : 'ghost'} size="sm"
                className="px-2.5 h-7" onClick={() => setViewMode('slider')}>
                <SlidersHorizontal className="w-4 h-4" />
              </Button>
            </div>

            {/* 差异图 */}
            <Button variant={showDiff ? 'default' : 'outline'} size="sm"
              className="gap-1.5 px-3 h-8" onClick={toggleDiff}
              disabled={!pair?.diff_url}>
              {showDiff ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
              <span className="text-xs">差异图</span>
            </Button>

            {/* 缩放 */}
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="sm" className="px-2 h-8"
                onClick={() => setZoom(Math.max(0.25, zoom - 0.25))}>
                <ZoomOut className="w-4 h-4" />
              </Button>
              <span className="text-xs text-gray-500 w-10 text-center">{Math.round(zoom * 100)}%</span>
              <Button variant="ghost" size="sm" className="px-2 h-8"
                onClick={() => setZoom(Math.min(4, zoom + 0.25))}>
                <ZoomIn className="w-4 h-4" />
              </Button>
              <Button variant="ghost" size="sm" className="px-2 h-8" onClick={() => setZoom(1)}>
                <RotateCcw className="w-3.5 h-3.5" />
              </Button>
            </div>
          </header>

          {/* ── 主体 ────────────────────────────────────────────────────── */}
          <div className="flex flex-1 overflow-hidden bg-gray-100">
            {/* 对比视图 */}
            <div className="flex-1 flex flex-col overflow-hidden">
              {pairLoading ? (
                <div className="flex-1 flex items-center justify-center">
                  <Loader2 className="w-8 h-8 animate-spin text-primary" />
                </div>
              ) : pair ? (
                viewMode === 'side-by-side'
                  ? <ModalSideBySide pair={pair} showDiff={showDiff} zoom={zoom} />
                  : <ModalSlider     pair={pair} showDiff={showDiff} zoom={zoom} />
              ) : (
                <div className="flex-1 flex items-center justify-center text-gray-400">
                  暂无对比数据
                </div>
              )}
            </div>

            {/* 右侧信息面板 */}
            {pair && (
              <aside className="w-56 bg-white border-l border-gray-200 p-4 overflow-y-auto shrink-0">
                <ModalInfoPanel pair={pair} pairIndex={localIdx} diffAlgo={diffAlgo} />
              </aside>
            )}
          </div>
        </div>
      </div>
    </TooltipProvider>
  )
}

// ─── 弹窗内并排视图 ────────────────────────────────────────────────────────
function ModalSideBySide({ pair, showDiff, zoom }: { pair: DiffPairResponse; showDiff: boolean; zoom: number }) {
  return (
    <div className="flex-1 flex gap-0.5 bg-[#1a1a2e] overflow-hidden">
      <ModalImagePane url={showDiff && pair.diff_url ? pair.diff_url : pair.image_a?.url} label="A" zoom={zoom} placeholder={!pair.image_a} />
      <ModalImagePane url={pair.image_b?.url} label="B" zoom={zoom} placeholder={!pair.image_b} />
    </div>
  )
}

// ─── 弹窗内滑块视图 ────────────────────────────────────────────────────────
function ModalSlider({ pair, showDiff, zoom }: { pair: DiffPairResponse; showDiff: boolean; zoom: number }) {
  const [pos, setPos] = useState(50)
  const ref = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  const calcPos = (cx: number) => {
    const rect = ref.current?.getBoundingClientRect()
    if (!rect) return
    setPos(Math.min(100, Math.max(0, ((cx - rect.left) / rect.width) * 100)))
  }
  const urlA = showDiff && pair.diff_url ? pair.diff_url : pair.image_a?.url
  return (
    <div ref={ref} className="flex-1 overflow-auto bg-[#1a1a2e] select-none"
      onMouseMove={(e) => dragging.current && calcPos(e.clientX)}
      onMouseDown={(e) => { dragging.current = true; calcPos(e.clientX) }}
      onMouseUp={() => { dragging.current = false }}
      onMouseLeave={() => { dragging.current = false }}>
      <div className="flex flex-col items-center py-4 min-w-full">
        <div className="relative" style={{ width: `${zoom * 100}%` }}>
          {pair.image_b?.url && <img src={pair.image_b.url} alt="B" draggable={false} style={{ display:'block', width:'100%', height:'auto' }} />}
          <div className="absolute inset-0 overflow-hidden" style={{ width: `${pos}%` }}>
            {urlA && <img src={urlA} alt="A" draggable={false} style={{ display:'block', width: `${10000/pos}%`, height:'auto', maxWidth:'none' }} />}
          </div>
          <div className="absolute top-0 bottom-0 w-0.5 bg-white shadow-lg z-20 cursor-col-resize" style={{ left:`${pos}%`, transform:'translateX(-50%)' }}>
            <div className="sticky top-1/2 -translate-y-1/2 -translate-x-[calc(50%-1px)] w-9 h-9 rounded-full bg-white shadow-xl flex items-center justify-center border border-gray-200 pointer-events-none">
              <div className="flex gap-0.5"><div className="w-0.5 h-4 bg-gray-400 rounded" /><div className="w-0.5 h-4 bg-gray-400 rounded" /></div>
            </div>
          </div>
          <div className="absolute top-2 left-2 bg-cyan-600 text-white text-xs font-bold px-2 py-0.5 rounded z-10 pointer-events-none">A</div>
          <div className="absolute top-2 right-2 bg-violet-600 text-white text-xs font-bold px-2 py-0.5 rounded z-10 pointer-events-none">B</div>
        </div>
      </div>
    </div>
  )
}

// ─── 弹窗内图片面板 ────────────────────────────────────────────────────────
function ModalImagePane({ url, label, zoom, placeholder }: { url?: string; label: string; zoom: number; placeholder?: boolean }) {
  const col = label === 'A' ? 'bg-cyan-600' : 'bg-violet-600'
  return (
    <div className="flex-1 overflow-auto relative bg-[#1a1a2e] select-none">
      <div className={`sticky top-2 left-2 z-10 inline-block ${col} text-white text-xs font-bold px-2 py-0.5 rounded ml-2`}>{label}</div>
      {placeholder ? (
        <div className="flex items-center justify-center h-40 text-gray-500 text-sm">待对比</div>
      ) : url ? (
        <div className="flex flex-col items-center py-4 min-w-full">
          <img src={url} alt={label} draggable={false} style={{ display:'block', width:`${zoom*100}%`, height:'auto', maxWidth:'none' }} />
        </div>
      ) : (
        <div className="flex items-center justify-center h-40 text-gray-500 text-sm gap-2">
          <Loader2 className="w-4 h-4 animate-spin" />计算中…
        </div>
      )}
    </div>
  )
}

// ─── 弹窗内信息面板 ────────────────────────────────────────────────────────
function ModalInfoPanel({ pair, pairIndex, diffAlgo }: { pair: DiffPairResponse; pairIndex: number; diffAlgo: string }) {
  const score    = pair.diff_score
  const isSimilar = pair.is_similar !== null && pair.is_similar !== undefined
    ? pair.is_similar
    : score !== undefined ? score >= 0.75 : undefined
  const scoreColor = !score ? 'text-gray-400' : score >= 0.75 ? 'text-green-600' : 'text-red-500'
  const scoreLabel = !score ? '—' : score >= 0.90 ? '相似度高' : score >= 0.75 ? '相似' : score >= 0.50 ? '差异显著' : '差异很大'
  const stMap: Record<string, { label: string; color: string }> = {
    pending: { label:'待计算', color:'text-gray-500' },
    running: { label:'计算中', color:'text-cyan-600' },
    done:    { label:'已完成', color:'text-green-600' },
    failed:  { label:'失败',   color:'text-red-500' },
  }
  const st = stMap[pair.status] ?? stMap.pending
  return (
    <div className="space-y-5 text-sm">
      <div>
        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-2">对比信息</p>
        <div className="space-y-2">
          <Row label="当前对" value={`第 ${pairIndex+1} 对`} />
          <Row label="状态"><span className={`text-xs font-medium ${st.color}`}>{st.label}</span></Row>
        </div>
      </div>
      {pair.status === 'done' && (
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-2">差异分析</p>
          <div className="space-y-2">
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-gray-400">相似度</span>
                <div className="flex items-center gap-1.5">
                  {isSimilar === false && <span className="text-[10px] font-semibold bg-red-100 text-red-600 px-1.5 py-0.5 rounded">差异显著</span>}
                  <span className={`text-sm font-semibold ${scoreColor}`}>{score ? `${(score*100).toFixed(1)}%` : '—'}</span>
                </div>
              </div>
              {score !== undefined && (
                <>
                  <div className="w-full bg-gray-100 rounded-full h-1.5">
                    <div className={`h-1.5 rounded-full ${score >= 0.75 ? 'bg-green-500' : 'bg-red-500'}`} style={{ width:`${score*100}%` }} />
                  </div>
                  <div className="relative w-full h-0">
                    <div className="absolute top-[-6px] w-px h-2 bg-gray-400 opacity-60" style={{ left:'75%' }} />
                    <span className="absolute top-[-4px] text-[9px] text-gray-400" style={{ left:'calc(75% + 2px)' }}>75%</span>
                  </div>
                  <p className={`text-xs mt-3 ${scoreColor}`}>{scoreLabel}</p>
                </>
              )}
            </div>
            <Row label="对齐方式" value={
              pair.align_method === 'resize' ? '缩放对齐'
              : pair.align_method === 'feature' ? 'ORB特征配准'
              : '无需对齐'
            } />
            <Row label="对比策略" value={
              DIFF_ALGO_CONFIG[diffAlgo as DiffAlgo]?.label ?? '均衡模式'
            } />
          </div>
        </div>
      )}
      {pair.size_warning && (
        <div className="flex items-start gap-2 bg-amber-50 rounded-lg p-3">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-700">两图尺寸差异较大，结果仅供参考</p>
        </div>
      )}
      <div>
        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-2">图片信息</p>
        <div className="space-y-2">
          {pair.image_a && <><Row label="A" value={pair.image_a.original_name} truncate />{pair.image_a.width && <Row label="A尺寸" value={`${pair.image_a.width}×${pair.image_a.height}`} />}</>}
          {pair.image_b && <><Row label="B" value={pair.image_b.original_name} truncate />{pair.image_b.width && <Row label="B尺寸" value={`${pair.image_b.width}×${pair.image_b.height}`} />}</>}
        </div>
      </div>
      <p className="text-[10px] text-gray-400">按 ← → 键切换 · Esc 关闭</p>
    </div>
  )
}

function Row({ label, value, children, truncate }: { label: string; value?: string; children?: React.ReactNode; truncate?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-2">
      <span className="text-xs text-gray-400 shrink-0">{label}</span>
      {children ?? <span className={`text-xs text-gray-700 font-medium text-right ${truncate ? 'truncate max-w-[120px]' : ''}`}>{value}</span>}
    </div>
  )
}
