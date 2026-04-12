import client from './client'
import type { DiffStatusResponse, DiffPairResponse } from '@/types'

export const diffApi = {
  status: (taskId: number) =>
    client.get<DiffStatusResponse>(`/tasks/${taskId}/diff-status`).then((r) => r.data),

  pair: (taskId: number, pairIndex: number) =>
    client.get<DiffPairResponse>(`/tasks/${taskId}/diff/${pairIndex}`).then((r) => r.data),

  getPair: (taskId: number, pairIndex: number) =>
    client.get<DiffPairResponse>(`/tasks/${taskId}/diff/${pairIndex}`).then((r) => r.data),

  compute: (taskId: number) =>
    client.post(`/tasks/${taskId}/diff/compute`).then((r) => r.data),

  /** 获取报告下载 URL（直接 window.open 或 fetch blob） */
  reportUrl: (taskId: number) =>
    `/api/v1/tasks/${taskId}/report`,
}
