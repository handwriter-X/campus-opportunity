export type OpportunityStatus = 'new' | 'following' | 'ignored'

export interface OpportunityItem {
  id: string
  title: string
  summary: string
  source: string
  sourceUrl?: string
  publishTime: string
  tags: string[]
  /** Agent 评估的机会分 0-100 */
  score: number
  aiInsight?: string
  status: OpportunityStatus
}

export interface OpportunityPool {
  id: string
  title: string
  description: string
  updatedAt: string
  items: OpportunityItem[]
}

export type AgentActionType = 'follow' | 'ignore' | 'deep_analyze' | 'draft_followup'

export interface AgentActionPayload {
  poolId: string
  itemId: string
  action: AgentActionType
  userCode?: string
}

export interface AgentActionResult {
  message: string
  status?: OpportunityStatus
  insight?: string
}

export interface AgentChatPayload {
  poolId: string
  question: string
  userCode?: string
}

export interface AgentChatResult {
  answer: string
}

export interface ApiResponse<T> {
  code: number // 0 表示成功
  message: string
  data: T
}