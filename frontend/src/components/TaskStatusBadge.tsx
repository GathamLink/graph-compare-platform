import { Badge } from '@/components/ui/badge'
import type { TaskStatus } from '@/types'

const config: Record<TaskStatus, { label: string; className: string }> = {
  draft:     { label: '草稿',   className: 'bg-gray-100 text-gray-600 hover:bg-gray-100' },
  active:    { label: '进行中', className: 'bg-cyan-100 text-cyan-700 hover:bg-cyan-100' },
  completed: { label: '已完成', className: 'bg-green-100 text-green-700 hover:bg-green-100' },
}

export default function TaskStatusBadge({ status }: { status: TaskStatus }) {
  const { label, className } = config[status]
  return <Badge className={`text-xs font-medium ${className}`}>{label}</Badge>
}
