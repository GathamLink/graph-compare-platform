import client from './client'
import type { Task, TaskDetail, TaskListResponse, CreateTaskDto, UpdateTaskDto } from '@/types'

/** 过滤掉值为 undefined / null / 空字符串 的参数，避免把无效 query 带给后端 */
function cleanParams(params?: Record<string, any>) {
  if (!params) return undefined
  return Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  )
}

export const taskApi = {
  list: (params?: { page?: number; page_size?: number; search?: string; status?: string }) =>
    client.get<TaskListResponse>('/tasks', { params: cleanParams(params) }).then((r) => r.data),

  get: (id: number) =>
    client.get<TaskDetail>(`/tasks/${id}`).then((r) => r.data),

  create: (data: CreateTaskDto) =>
    client.post<Task>('/tasks', data).then((r) => r.data),

  update: (id: number, data: UpdateTaskDto) =>
    client.put<Task>(`/tasks/${id}`, data).then((r) => r.data),

  delete: (id: number) =>
    client.delete(`/tasks/${id}`).then((r) => r.data),
}
