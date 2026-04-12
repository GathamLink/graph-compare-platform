// ─── 任务相关 ──────────────────────────────────────────────────────────────────
export type TaskStatus = 'draft' | 'active' | 'completed'
export type PairMode = 'sequential' | 'prefix'
export type DiffAlgo = 'balanced' | 'document' | 'structural' | 'pixel_exact'

export const DIFF_ALGO_CONFIG: Record<DiffAlgo, {
  label: string
  icon: string
  desc: string
  tip: string
}> = {
  balanced: {
    label: '标准模式',
    icon:  '⚖️',
    desc:  '适合 App UI 截图、通用图片对比',
    tip:   '综合感知像素差异与页面结构，是大多数场景下的首选方案',
  },
  document: {
    label: '文档对比',
    icon:  '📄',
    desc:  '适合 PDF / 文档导出图片对比',
    tip:   '使用高精度插值与严格阈值，能检测 DPI 差异、字体渲染细节等细微变化',
  },
  structural: {
    label: '结构探测',
    icon:  '🔍',
    desc:  '适合检测页面布局、元素增删变化',
    tip:   '侧重感知整体区域的结构差异，适合排查模块消失、内容错位等问题',
  },
  pixel_exact: {
    label: '像素级精确',
    icon:  '🔬',
    desc:  '适合验证导出结果是否完全一致',
    tip:   '对任意像素差异均敏感，DPI 变化、轻微渲染差异均会被检测到',
  },
}

export interface Task {
  id: number
  name: string
  description?: string
  status: TaskStatus
  pair_mode: PairMode
  diff_algo: DiffAlgo
  pair_count: number
  created_at: string
  updated_at: string
}

export interface ImageBrief {
  id: number
  image_id: number
  sort_order: number
  original_name: string
  url: string
  thumb_url?: string    // 200px 宽缩略图，无时降级为 url
  width?: number
  height?: number
}

export interface TaskDetail extends Task {
  group_a: ImageBrief[]
  group_b: ImageBrief[]
}

// ─── 差异相关 ──────────────────────────────────────────────────────────────────
export type DiffStatus = 'pending' | 'running' | 'done' | 'failed'
/** resize：缩放对齐；feature：ORB特征点配准（用于大比例尺寸差异） */
export type AlignMethod = 'resize' | 'feature' | 'none'

export interface DiffStatusResponse {
  task_id: number
  total: number
  done: number
  running: number
  pending: number
  failed: number
}

export interface DiffPairResponse {
  pair_index: number
  pair_key?: string          // prefix 模式下的配对前缀
  status: DiffStatus
  image_a?: ImageBrief
  image_b?: ImageBrief
  diff_url?: string
  diff_score?: number        // 0~1，信息区掩码四指标融合分数（越高越相似）
  is_similar?: boolean | null  // true=相似(≥75%)；false=差异显著(<75%)；null=未计算
  align_method?: AlignMethod
  size_warning: boolean
}

// ─── API 请求/响应 ────────────────────────────────────────────────────────────
export interface CreateTaskDto {
  name: string
  description?: string
  pair_mode?: PairMode
  diff_algo?: DiffAlgo
}

export interface UpdateTaskDto {
  name?: string
  description?: string
  status?: TaskStatus
  pair_mode?: PairMode
  diff_algo?: DiffAlgo
}

export interface BatchAppendResult {
  task_id: number
  appended: {
    group_a: ImageBrief[]
    group_b: ImageBrief[]
  }
  diff_triggered: boolean
}

export interface TaskListResponse {
  items: Task[]
  total: number
  page: number
  page_size: number
}

export interface ApiError {
  code: number
  message: string
  detail?: string
}
