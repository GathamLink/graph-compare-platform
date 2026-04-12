import axios from 'axios'
import type { ApiError } from '@/types'

const client = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

client.interceptors.response.use(
  (res) => res,
  (err) => {
    const data: ApiError = err.response?.data ?? { code: 500, message: '网络错误，请稍后重试' }
    return Promise.reject(data)
  }
)

export default client
