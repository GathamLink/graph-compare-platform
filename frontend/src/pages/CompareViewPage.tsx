import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft, ChevronLeft, ChevronRight, Columns2, SlidersHorizontal,
  Eye, EyeOff, ZoomIn, ZoomOut, RotateCcw, AlertTriangle, Loader2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useTaskStore } from '@/store/taskStore'
import { useCompareStore } from '@/store/compareStore'
import type { DiffPairResponse } from '@/types'

export default function CompareViewPage() {
  const { id, pairIndex: pairParam } = useParams<{ id: string; pairIndex?: string }>()
  const taskId = Number(id)
  const navigate = useNavigate()

  const { currentTask, fetchTask } = useTaskStore()
  const {
    currentPairIndex, viewMode, showDiff, zoom,
    setCurrentPair, setViewMode, toggleDiff, setZoom,
    fetchPair, currentPairData, pairLoading, startPolling,
  } = useCompareStore()

  const pairCount = currentTask
    ? Math.max(currentTask.group_a.length, currentTask.group_b.length)
    : 0

  // 初始化
  useEffect(() => {
    if (!currentTask || currentTask.id !== taskId) fetchTask(taskId)
  }, [taskId])

  useEffect(() => {
    const idx = pairParam !== undefined ? Number(pairParam) : 0
    setCurrentPair(idx)
  }, [pairParam])

  // 启动轮询
  useEffect(() => {
    if (!currentTask) return
    const stop = startPolling(taskId)
    return stop
  }, [currentTask?.id])

  // 切换对时拉取数据
  useEffect(() => {
    if (currentTask) fetchPair(taskId, currentPairIndex)
  }, [currentPairIndex, taskId, currentTask?.id])

  // 键盘导航
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft' && currentPairIndex > 0) {
        navigate(`/tasks/${taskId}/compare/${currentPairIndex - 1}`)
        setCurrentPair(currentPairIndex - 1)
      }
      if (e.key === 'ArrowRight' && currentPairIndex < pairCount - 1) {
        navigate(`/tasks/${taskId}/compare/${currentPairIndex + 1}`)
        setCurrentPair(currentPairIndex + 1)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [currentPairIndex, pairCount])

  const goTo = (idx: number) => {
    setCurrentPair(idx)
    navigate(`/tasks/${taskId}/compare/${idx}`)
  }

  if (!currentTask) {
    return (
      <div className="h-screen flex flex-col">
        <div className="h-14 border-b bg-white flex items-center px-4 gap-3">
          <Skeleton className="h-8 w-24" />
          <Skeleton className="h-6 w-48" />
        </div>
        <Skeleton className="flex-1 m-4 rounded-xl" />
      </div>
    )
  }

  return (
    <TooltipProvider>
      <div className="h-screen flex flex-col bg-gray-100 overflow-hidden">
        {/* ── 顶部工具栏 ───────────────────────────────────────────────── */}
        <header className="h-14 bg-white border-b border-gray-200 flex items-center px-4 gap-3 shrink-0 z-30">
          <Button variant="ghost" size="sm" className="gap-1.5 text-gray-600 shrink-0"
            onClick={() => navigate(`/tasks/${taskId}`)}>
            <ArrowLeft className="w-4 h-4" />
            <span className="hidden sm:inline">返回</span>
          </Button>

          <div className="h-5 w-px bg-gray-200" />

          {/* 任务名 */}
          <span className="text-sm font-medium text-gray-700 truncate max-w-[180px] hidden sm:block">
            {currentTask.name}
          </span>

          <div className="h-5 w-px bg-gray-200 hidden sm:block" />

          {/* 对数导航 */}
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" className="px-2" disabled={currentPairIndex === 0}
              onClick={() => goTo(currentPairIndex - 1)}>
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <span className="text-sm font-medium text-gray-700 min-w-[72px] text-center">
              {currentPairIndex + 1} / {pairCount}
            </span>
            <Button variant="ghost" size="sm" className="px-2" disabled={currentPairIndex >= pairCount - 1}
              onClick={() => goTo(currentPairIndex + 1)}>
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>

          <div className="flex-1" />

          {/* 视图模式切换 */}
          <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant={viewMode === 'side-by-side' ? 'default' : 'ghost'}
                  size="sm" className="px-2.5 h-7"
                  onClick={() => setViewMode('side-by-side')}
                >
                  <Columns2 className="w-4 h-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>并排对比</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant={viewMode === 'slider' ? 'default' : 'ghost'}
                  size="sm" className="px-2.5 h-7"
                  onClick={() => setViewMode('slider')}
                >
                  <SlidersHorizontal className="w-4 h-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>滑块叠加</TooltipContent>
            </Tooltip>
          </div>

          {/* 差异图开关 */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={showDiff ? 'default' : 'outline'}
                size="sm" className="gap-1.5 px-3 h-8"
                onClick={toggleDiff}
                disabled={!currentPairData?.diff_url}
              >
                {showDiff ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
                <span className="text-xs">差异图</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>{currentPairData?.diff_url ? (showDiff ? '隐藏差异标注' : '显示差异标注') : '差异图计算中...'}</TooltipContent>
          </Tooltip>

          {/* 缩放 */}
          <div className="flex items-center gap-1">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="sm" className="px-2 h-8"
                  onClick={() => setZoom(Math.max(0.25, zoom - 0.25))}>
                  <ZoomOut className="w-4 h-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>缩小</TooltipContent>
            </Tooltip>
            <span className="text-xs text-gray-500 w-10 text-center">{Math.round(zoom * 100)}%</span>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="sm" className="px-2 h-8"
                  onClick={() => setZoom(Math.min(4, zoom + 0.25))}>
                  <ZoomIn className="w-4 h-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>放大</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="sm" className="px-2 h-8" onClick={() => setZoom(1)}>
                  <RotateCcw className="w-3.5 h-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>重置缩放</TooltipContent>
            </Tooltip>
          </div>
        </header>

        {/* ── 主体区域 ──────────────────────────────────────────────────── */}
        <div className="flex flex-1 overflow-hidden">
          {/* 左侧缩略图导航 */}
          <aside className="w-20 bg-white border-r border-gray-200 flex flex-col gap-1.5 p-2 overflow-y-auto shrink-0">
            {Array.from({ length: pairCount }).map((_, i) => {
              const imgA = currentTask.group_a[i]
              return (
                <button
                  key={i}
                  onClick={() => goTo(i)}
                  className={`relative w-full aspect-square rounded-lg overflow-hidden bg-gray-100 border-2 transition-all ${
                    i === currentPairIndex ? 'border-primary thumb-active' : 'border-transparent hover:border-gray-300'
                  }`}
                >
                  {imgA ? (
                    <img src={imgA.url} alt="" className="w-full h-full object-cover" loading="lazy" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-xs text-gray-400">{i + 1}</div>
                  )}
                  <span className="absolute bottom-0 left-0 right-0 bg-black/50 text-white text-[9px] text-center py-0.5">
                    {i + 1}
                  </span>
                </button>
              )
            })}
          </aside>

          {/* 对比视图主区域 */}
          <div className="flex-1 flex flex-col overflow-hidden">
            {pairLoading ? (
              <div className="flex-1 flex items-center justify-center">
                <Loader2 className="w-8 h-8 animate-spin text-primary" />
              </div>
            ) : currentPairData ? (
              viewMode === 'side-by-side'
                ? <SideBySideView pair={currentPairData} showDiff={showDiff} zoom={zoom} />
                : <SliderView pair={currentPairData} showDiff={showDiff} zoom={zoom} />
            ) : (
              <div className="flex-1 flex items-center justify-center text-gray-400">
                <p>暂无对比数据</p>
              </div>
            )}
          </div>

          {/* 右侧信息面板 */}
          {currentPairData && (
            <aside className="w-56 bg-white border-l border-gray-200 p-4 overflow-y-auto shrink-0">
              <DiffInfoPanel
                pair={currentPairData}
                pairIndex={currentPairIndex}
                diffAlgo={currentTask?.diff_algo ?? 'balanced'}
              />
            </aside>
          )}
        </div>
      </div>
    </TooltipProvider>
  )
}

/* ── 并排对比视图 ─────────────────────────────────────────────────────────── */
function SideBySideView({ pair, showDiff, zoom }: { pair: DiffPairResponse; showDiff: boolean; zoom: number }) {
  return (
    <div className="flex-1 flex gap-0.5 bg-gray-700 overflow-hidden">
      <ImagePane
        url={showDiff && pair.diff_url ? pair.diff_url : pair.image_a?.url}
        label="A"
        originalName={pair.image_a?.original_name}
        zoom={zoom}
        placeholder={!pair.image_a}
      />
      <ImagePane
        url={pair.image_b?.url}
        label="B"
        originalName={pair.image_b?.original_name}
        zoom={zoom}
        placeholder={!pair.image_b}
      />
    </div>
  )
}

/* ── 单侧图片面板 ─────────────────────────────────────────────────────────── */
function ImagePane({ url, label, originalName, zoom, placeholder }: {
  url?: string; label: string; originalName?: string; zoom: number; placeholder?: boolean
}) {
  const labelColor = label === 'A' ? 'bg-cyan-600' : 'bg-violet-600'

  return (
    /* 外层：占满可用空间，overflow-auto 提供双向滚动条 */
    <div className="flex-1 overflow-auto relative bg-[#1a1a2e] select-none">

      {/* 标签（sticky 在视口左上角始终可见） */}
      <div className={`sticky top-2 left-2 z-10 inline-block ${labelColor} text-white text-xs font-bold px-2 py-0.5 rounded ml-2`}>
        {label}
      </div>

      {placeholder ? (
        <div className="flex items-center justify-center h-full text-gray-500 text-sm mt-[-1.5rem]">
          待对比
        </div>
      ) : url ? (
        /*
         * 内层：
         *   - min-w-full min-h-full 保证撑满外层（外层不会塌陷）
         *   - flex flex-col items-center 让图片水平居中
         *   - zoom < 1 时图片小于容器 → 居中展示；zoom > 1 时图片超出 → 外层出滚动条
         */
        <div className="flex flex-col items-center py-4 min-w-full">
          <img
            src={url}
            alt={originalName ?? ''}
            draggable={false}
            style={{
              display: 'block',
              width: `${zoom * 100}%`,   /* 相对于这个 flex 容器宽度（=外层容器宽） */
              height: 'auto',
              maxWidth: 'none',
              flexShrink: 0,
            }}
          />
          {originalName && (
            <div className="mt-2 mb-1">
              <span className="bg-black/50 text-white text-xs px-2 py-0.5 rounded truncate inline-block max-w-[90vw]">
                {originalName}
              </span>
            </div>
          )}
        </div>
      ) : (
        <div className="flex items-center justify-center h-40 text-gray-500 text-sm gap-2">
          <Loader2 className="w-4 h-4 animate-spin" />
          计算中...
        </div>
      )}
    </div>
  )
}

/* ── 滑块叠加视图 ─────────────────────────────────────────────────────────── */
function SliderView({ pair, showDiff, zoom }: { pair: DiffPairResponse; showDiff: boolean; zoom: number }) {
  const [sliderPos, setSliderPos] = useState(50)
  const containerRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  // 计算滑块位置（基于容器左边缘）
  const calcPos = (clientX: number) => {
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) return
    const pct = Math.min(100, Math.max(0, ((clientX - rect.left) / rect.width) * 100))
    setSliderPos(pct)
  }

  const urlA = showDiff && pair.diff_url ? pair.diff_url : pair.image_a?.url
  const urlB = pair.image_b?.url

  return (
    /* 外层：撑满，overflow-auto，捕获拖拽事件 */
    <div
      ref={containerRef}
      className="flex-1 overflow-auto bg-[#1a1a2e] select-none"
      onMouseMove={(e) => dragging.current && calcPos(e.clientX)}
      onMouseDown={(e) => { dragging.current = true; calcPos(e.clientX) }}
      onMouseUp={() => { dragging.current = false }}
      onMouseLeave={() => { dragging.current = false }}
    >
      {/*
       * 内层：flex items-center 居中；min-w-full 保证不塌陷
       * py-4 给上下留白，图片层 relative 用于绝对定位 A 图覆盖
       */}
      <div className="flex flex-col items-center py-4 min-w-full">
        {/* 图片组合层：相对定位，宽度由 zoom 决定 */}
        <div
          className="relative"
          style={{ width: `${zoom * 100}%`, flexShrink: 0 }}
        >
          {/* B 图（底层基准） */}
          {urlB && (
            <img src={urlB} alt="B" draggable={false}
              style={{ display: 'block', width: '100%', height: 'auto' }}
            />
          )}

          {/* A 图（绝对覆盖，按 sliderPos 裁剪到左侧） */}
          <div
            className="absolute inset-0 overflow-hidden"
            style={{ width: `${sliderPos}%` }}
          >
            {urlA && (
              <img src={urlA} alt="A" draggable={false}
                style={{
                  display: 'block',
                  // 图片本身宽度要等于父层 100%（即完整宽），clip 交给外层 overflow-hidden
                  width: `${10000 / sliderPos}%`,
                  height: 'auto',
                  maxWidth: 'none',
                }}
              />
            )}
          </div>

          {/* 分割线 + 拖柄 */}
          <div
            className="absolute top-0 bottom-0 w-0.5 bg-white shadow-lg z-20 cursor-col-resize"
            style={{ left: `${sliderPos}%`, transform: 'translateX(-50%)' }}
          >
            <div className="sticky top-1/2 -translate-y-1/2 -translate-x-[calc(50%-1px)] w-9 h-9 rounded-full bg-white shadow-xl flex items-center justify-center border border-gray-200 pointer-events-none">
              <div className="flex gap-0.5">
                <div className="w-0.5 h-4 bg-gray-400 rounded" />
                <div className="w-0.5 h-4 bg-gray-400 rounded" />
              </div>
            </div>
          </div>

          {/* A/B 标签 */}
          <div className="absolute top-2 left-2 bg-cyan-600 text-white text-xs font-bold px-2 py-0.5 rounded z-10 pointer-events-none">A</div>
          <div className="absolute top-2 right-2 bg-violet-600 text-white text-xs font-bold px-2 py-0.5 rounded z-10 pointer-events-none">B</div>
        </div>
      </div>
    </div>
  )
}

/* ── 差异信息面板 ─────────────────────────────────────────────────────────── */
function DiffInfoPanel({ pair, pairIndex, diffAlgo }: {
  pair: DiffPairResponse
  pairIndex: number
  diffAlgo?: string
}) {
  const statusMap: Record<string, { label: string; color: string }> = {
    pending: { label: '待计算', color: 'text-gray-500' },
    running: { label: '计算中', color: 'text-cyan-600' },
    done:    { label: '已完成', color: 'text-green-600' },
    failed:  { label: '失败',   color: 'text-red-500' },
  }
  const st = statusMap[pair.status] ?? statusMap.pending

  const score = pair.diff_score
  // 阈值 75%（与后端 SIMILARITY_THRESHOLD=0.75 对齐）
  // is_similar 优先用后端判断；后端未返回时降级到前端阈值
  const isSimilar = pair.is_similar !== undefined && pair.is_similar !== null
    ? pair.is_similar
    : score !== undefined ? score >= 0.75 : undefined

  const scoreColor = score === undefined ? 'text-gray-400'
    : score >= 0.75 ? 'text-green-600'
    : 'text-red-500'

  const scoreLabel = score === undefined ? '—'
    : score >= 0.90 ? '相似度高'
    : score >= 0.75 ? '相似'
    : score >= 0.50 ? '差异显著'
    : '差异很大'

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">对比信息</h3>
        <div className="space-y-2.5">
          <InfoRow label="当前对" value={`第 ${pairIndex + 1} 对`} />
          <InfoRow label="计算状态">
            <span className={`text-xs font-medium ${st.color}`}>
              {st.label === '计算中' && <Loader2 className="w-3 h-3 animate-spin inline mr-1" />}
              {st.label}
            </span>
          </InfoRow>
        </div>
      </div>

      {pair.status === 'done' && (
        <div>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">差异分析</h3>
        <div className="space-y-2.5">
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-gray-500">相似度</span>
                <div className="flex items-center gap-1.5">
                  {isSimilar === false && (
                    <span className="text-[10px] font-semibold bg-red-100 text-red-600 px-1.5 py-0.5 rounded">
                      差异显著
                    </span>
                  )}
                  <span className={`text-sm font-semibold ${scoreColor}`}>
                    {score !== undefined ? `${(score * 100).toFixed(1)}%` : '—'}
                  </span>
                </div>
              </div>
              {score !== undefined && (
                <>
                  <div className="w-full bg-gray-100 rounded-full h-1.5">
                    <div
                      className={`h-1.5 rounded-full transition-all ${
                        score >= 0.75 ? 'bg-green-500' : 'bg-red-500'
                      }`}
                      style={{ width: `${score * 100}%` }}
                    />
                  </div>
                  {/* 75% 阈值刻度线 */}
                  <div className="relative w-full h-0">
                    <div className="absolute top-[-6px] w-px h-2 bg-gray-400 opacity-60" style={{ left: '75%' }} />
                    <span className="absolute top-[-4px] text-[9px] text-gray-400" style={{ left: 'calc(75% + 2px)' }}>75%</span>
                  </div>
                  <p className={`text-xs mt-3 ${scoreColor}`}>{scoreLabel}</p>
                </>
              )}
            </div>
            <InfoRow label="对齐方式" value={
              pair.align_method === 'resize'  ? '缩放对齐（宽高比相近）'
              : pair.align_method === 'feature' ? 'ORB特征点配准（大尺寸差异）'
              : pair.align_method === 'none'    ? '无需对齐'
              : '—'
            } />
            <InfoRow label="对比策略" value={
              diffAlgo === 'balanced'   ? '均衡（4:4）'
              : diffAlgo === 'pixel'    ? '像素优先（5:3）'
              : diffAlgo === 'structural' ? '结构优先（3:5）'
              : '均衡（4:4）'
            } />
          </div>
        </div>
      )}

      {pair.size_warning && (
        <div className="flex items-start gap-2 bg-amber-50 rounded-lg p-3">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-700">两图尺寸差异较大，对比结果仅供参考</p>
        </div>
      )}

      <div>
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">图片信息</h3>
        <div className="space-y-2.5">
          {pair.image_a && (
            <>
              <InfoRow label="A 文件" value={pair.image_a.original_name} truncate />
              {pair.image_a.width && <InfoRow label="A 尺寸" value={`${pair.image_a.width}×${pair.image_a.height}`} />}
            </>
          )}
          {pair.image_b && (
            <>
              <InfoRow label="B 文件" value={pair.image_b.original_name} truncate />
              {pair.image_b.width && <InfoRow label="B 尺寸" value={`${pair.image_b.width}×${pair.image_b.height}`} />}
            </>
          )}
        </div>
      </div>

      <p className="text-[10px] text-gray-400 leading-relaxed">
        按 ← → 键切换上/下一对图片
      </p>
    </div>
  )
}

function InfoRow({ label, value, children, truncate }: {
  label: string; value?: string; children?: React.ReactNode; truncate?: boolean
}) {
  return (
    <div className="flex items-start justify-between gap-2">
      <span className="text-xs text-gray-400 shrink-0">{label}</span>
      {children ?? (
        <span className={`text-xs text-gray-700 font-medium text-right ${truncate ? 'truncate max-w-[120px]' : ''}`}>
          {value}
        </span>
      )}
    </div>
  )
}
