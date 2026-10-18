import Taro from '@tarojs/taro'
import { AGENT_CONFIG } from '@/config/agent'
import type { ApiResponse } from '@/types/opportunity'

interface AgentRequestOptions {
  method?: 'GET' | 'POST'
  data?: Record<string, unknown>
}

/** 统一请求：自动注入 Agent API ID / Key，统一错误处理 */
export async function agentRequest<T>(
  path: string,
  { method = 'POST', data }: AgentRequestOptions = {},
): Promise<T> {
  const { baseUrl, apiId, apiKey, timeout } = AGENT_CONFIG

  const res = await Taro.request<ApiResponse<T>>({
    url: `${baseUrl}${path}`,
    method,
    data,
    timeout,
    header: {
      'Content-Type': 'application/json',
      'X-Agent-Id': apiId,
      Authorization: `Bearer ${apiKey}`,
    },
  })

  if (res.statusCode < 200 || res.statusCode >= 300) {
    throw new Error(`网络请求失败（${res.statusCode}）`)
  }
  const body = res.data
  if (body.code !== 0) {
    throw new Error(body.message || 'Agent 返回异常')
  }
  return body.data
}