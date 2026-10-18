export type TeamStatus = '仍在招募' | '需求结束'

export interface TeamRequest {
  id: string
  /** 项目名称 */
  name: string
  /** 目前团队人数（展示为「已集结x人」） */
  currentCount: number
  /** 招募人数（展示为「需要招募x人」） */
  recruitCount: number
  /** 招募的角色，后端给什么文本就展示什么，如「前端设计、后端开发」 */
  roles: string
  /** 截止时间，格式 YYYY-MM-DD HH:mm */
  deadline: string
  /** 后端是否已将该需求标记为结束（与截止时间共同决定状态） */
  closed: boolean

  /* ---- 以下为详情字段，列表接口可带可不带，点击卡片时会再请求详情接口补全 ---- */
  description?: string   // 项目介绍
  requirements?: string  // 能力 / 经验要求
  duration?: string      // 预计项目周期
  publisherName?: string // 发布者姓名
  publishTime?: string   // 发布时间
}

export interface TeamWithStatus extends TeamRequest {
  status: TeamStatus
}

export interface TeamApplyPayload {
  teamId: string
  /** 申请留言（自我介绍 / 联系方式等） */
  message: string
  /** 飞书登录 code，后端可用来识别申请人 */
  userCode?: string
}

export interface TeamApplyResult {
  message?: string
}
