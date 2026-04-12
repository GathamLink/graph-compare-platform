import { create } from 'zustand'
import { taskApi } from '@/api/taskApi'
import type { Task, TaskDetail, CreateTaskDto, UpdateTaskDto } from '@/types'
import { toast } from 'sonner'

interface TaskStore {
  tasks: Task[]
  total: number
  loading: boolean
  currentTask: TaskDetail | null
  taskLoading: boolean
  fetchTasks: (params?: { search?: string; status?: string; page?: number }) => Promise<void>
  fetchTask: (id: number) => Promise<void>
  createTask: (data: CreateTaskDto) => Promise<Task>
  updateTask: (id: number, data: UpdateTaskDto) => Promise<void>
  deleteTask: (id: number) => Promise<void>
  refreshCurrentTask: () => Promise<void>
}

export const useTaskStore = create<TaskStore>((set, get) => ({
  tasks: [],
  total: 0,
  loading: false,
  currentTask: null,
  taskLoading: false,

  fetchTasks: async (params) => {
    set({ loading: true })
    try {
      const res = await taskApi.list(params)
      set({ tasks: res.items, total: res.total })
    } catch (e: any) {
      const msg = e?.detail ?? e?.message ?? '获取任务列表失败'
      toast.error(msg)
    } finally {
      set({ loading: false })
    }
  },

  fetchTask: async (id) => {
    set({ taskLoading: true })
    try {
      const task = await taskApi.get(id)
      set({ currentTask: task })
    } catch (e: any) {
      toast.error(e?.message ?? '获取任务详情失败')
    } finally {
      set({ taskLoading: false })
    }
  },

  createTask: async (data) => {
    const task = await taskApi.create(data)
    set((s) => ({ tasks: [task, ...s.tasks], total: s.total + 1 }))
    return task
  },

  updateTask: async (id, data) => {
    const updated = await taskApi.update(id, data)
    set((s) => ({
      tasks: s.tasks.map((t) => (t.id === id ? updated : t)),
      currentTask: s.currentTask?.id === id ? { ...s.currentTask, ...updated } : s.currentTask,
    }))
  },

  deleteTask: async (id) => {
    await taskApi.delete(id)
    set((s) => ({ tasks: s.tasks.filter((t) => t.id !== id), total: s.total - 1 }))
  },

  refreshCurrentTask: async () => {
    const id = get().currentTask?.id
    if (id) await get().fetchTask(id)
  },
}))
