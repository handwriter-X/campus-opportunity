export interface Activity {
  id: string
  /** 活动名称 */
  name: string
  /** 活动类型：竞赛 / 讲座 / 志愿实践 / 文体活动 / 招聘宣讲 ... */
  type: string
  /** 活动时间（展示用文本，如 "2026-10-25 14:00"） */
  activityTime: string
  /** 报名截止时间，格式固定为 "YYYY-MM-DD HH:mm"，用于计算状态和排序 */
  deadline: string
  /** 地点 */
  location: string
  /** 来源（发布单位 / 渠道） */
  source: string
  /** 活动具体介绍（仅在详情弹窗展示） */
  description: string
}

export type ActivityStatus = '可参与' | '已截止'

/** 带状态的活动（状态由前端根据截止时间实时计算） */
export interface ActivityWithStatus extends Activity {
  status: ActivityStatus
}