import client from './client'
import type { BatchAppendResult } from '@/types'

export const imageApi = {
  upload: (taskId: number, group: 'A' | 'B', files: File[]) => {
    const fd = new FormData()
    fd.append('group', group)
    files.forEach((f) => fd.append('files', f))
    return client.post(`/tasks/${taskId}/images`, fd).then((r) => r.data)
  },

  batchAppend: (taskId: number, imagesA: File[], imagesB: File[]) => {
    const fd = new FormData()
    imagesA.forEach((f) => fd.append('images_a', f))
    imagesB.forEach((f) => fd.append('images_b', f))
    return client.post<BatchAppendResult>(`/tasks/${taskId}/images/batch-append`, fd).then((r) => r.data)
  },

  /** ZIP 压缩包批量导入（结构：原图/ + 对比图/） */
  importZip: (taskId: number, zipFile: File) => {
    const fd = new FormData()
    fd.append('file', zipFile)
    return client.post<BatchAppendResult>(`/tasks/${taskId}/images/import-zip`, fd).then((r) => r.data)
  },

  delete: (taskId: number, imageId: number) =>
    client.delete(`/tasks/${taskId}/images/${imageId}`).then((r) => r.data),

  reorder: (taskId: number, group: 'A' | 'B', order: number[]) =>
    client.patch(`/tasks/${taskId}/images/reorder`, { group, order }).then((r) => r.data),
}
