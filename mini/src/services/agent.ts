import { AGENT_CONFIG, isAgentConfigured } from '@/config/agent'
import type { Activity } from '@/types/activity'
import { agentRequest } from './request'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const pad = (n: number) => ('0' + n).slice(-2)

/* ====================== 真实接口 ====================== */

/** 获取校园活动列表 */
export async function getActivities(): Promise<Activity[]> {
  if (!isAgentConfigured) {
    await sleep(400)
    return mockActivities()
  }
  const raw = await agentRequest<unknown>(AGENT_CONFIG.endpoints.activityList, { data: {} })

  // 兼容 data 直接是数组，或 { list: [] } / { items: [] } / { activities: [] }
  const arr: unknown[] = Array.isArray(raw)
    ? raw
    : ((raw as any)?.list ?? (raw as any)?.items ?? (raw as any)?.activities ?? [])

  return arr.map(normalizeActivity).filter((a): a is Activity => a !== null)
}

/* ====================== 数据适配层 ======================
 * 后端字段名不同的话，只改这里的别名列表即可。
 * 每项优先取靠前的字段名。
 */
export const pick = (o: any, keys: string[]): any => {
  for (const k of keys) {
    if (o?.[k] !== undefined && o?.[k] !== null && o?.[k] !== '') return o[k]
  }
  return undefined
}

/** 把各种时间格式统一成 "YYYY-MM-DD HH:mm"；解析不了返回空字符串 */
export function normalizeTime(v: unknown, dateOnlyDefault = '23:59'): string {
  if (v === undefined || v === null || v === '') return ''

  // 时间戳（秒或毫秒）
  if (typeof v === 'number') {
    const d = new Date(v < 1e12 ? v * 1000 : v)
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  }

  const s = String(v).trim()

  // 2026-10-20 / 2026/10/20 / 2026.10.20（只有日期）
  const dateOnly = s.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/)
  if (dateOnly) return `${dateOnly[1]}-${pad(+dateOnly[2])}-${pad(+dateOnly[3])} ${dateOnlyDefault}`

  // 2026-10-20 19:00 / 2026-10-20T19:00:00 / 2026/10/20 19:00:00
  const full = s.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})[ T](\d{1,2}):(\d{2})/)
  if (full) {
    return `${full[1]}-${pad(+full[2])}-${pad(+full[3])} ${pad(+full[4])}:${full[5]}`
  }

  // 其他情况（带时区的 ISO 等）交给 Date 解析
  const d = new Date(s)
  if (!isNaN(d.getTime())) {
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  }
  return ''
}

function normalizeActivity(raw: unknown, idx: number): Activity | null {
  const o: any = raw
  const name = pick(o, ['name', 'title', 'activityName', 'activity_name'])
  const deadline = normalizeTime(
    pick(o, ['deadline', 'registrationDeadline', 'registration_deadline', 'signupDeadline', 'signup_deadline', 'enrollEndTime']),
  )

  // 没有名称或没有有效截止时间的数据无法计算状态/排序，直接丢弃
  if (!name || !deadline) {
    console.warn('[agent] 丢弃无效活动数据（缺少名称或报名截止时间）:', raw)
    return null
  }

  return {
    id: String(pick(o, ['id', 'activityId', 'activity_id', 'uuid']) ?? `act-${idx}`),
    name: String(name),
    type: String(pick(o, ['type', 'category', 'activityType', 'activity_type']) ?? '其他'),
    activityTime:
      normalizeTime(pick(o, ['activityTime', 'activity_time', 'startTime', 'start_time', 'eventTime']), '00:00') || '待定',
    deadline,
    location: String(pick(o, ['location', 'place', 'address', 'venue']) ?? '待定'),
    source: String(pick(o, ['source', 'origin', 'publisher', 'sourceName', 'source_name']) ?? '未知来源'),
    description: String(pick(o, ['description', 'desc', 'content', 'summary', 'intro']) ?? '暂无活动介绍'),
  }
}

/* ====================== mock：未填写 API Key 时用于预览 UI ====================== */

/** 生成相对当前时间 offsetDays 天后的 "YYYY-MM-DD HH:mm" */
function at(offsetDays: number, hour = 18, minute = 0): string {
  const d = new Date()
  d.setDate(d.getDate() + offsetDays)
  d.setHours(hour, minute, 0, 0)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function mockActivities(): Activity[] {
  return [
    {
      id: 'a1',
      name: '全国大学生数学建模竞赛校内选拔赛',
      type: '竞赛',
      activityTime: at(12, 9, 0),
      deadline: at(2, 23, 59),
      location: '理学院报告厅 A301',
      source: '教务处',
      description:
        '面向全体本科生的校内选拔赛，3 人一队，比赛时长 72 小时。获奖队伍将代表学校参加全国赛，并获得创新学分。报名需提交队伍名单与指导老师信息，赛前将组织两次免费培训。',
    },
    {
      id: 'a2',
      name: '人工智能前沿讲座：大模型与智能体应用',
      type: '讲座',
      activityTime: at(5, 19, 0),
      deadline: at(1, 12, 0),
      location: '图书馆报告厅',
      source: '计算机学院',
      description:
        '邀请业内专家分享大模型在教育、科研与产业中的落地实践，并设有 30 分钟互动问答。名额 200 人，先到先得，现场签到可获得 2 学时第二课堂认证。',
    },
    {
      id: 'a3',
      name: '社区敬老志愿服务日',
      type: '志愿实践',
      activityTime: at(9, 8, 30),
      deadline: at(6, 18, 0),
      location: '阳光社区活动中心',
      source: '校团委',
      description:
        '走进社区开展陪伴聊天、智能手机教学与健康义诊协助。每位志愿者可获得 4 小时志愿时长，集合后统一乘车往返，请携带学生证。',
    },
    {
      id: 'a4',
      name: '校园十佳歌手大赛初赛',
      type: '文体活动',
      activityTime: at(15, 18, 30),
      deadline: at(10, 20, 0),
      location: '大学生活动中心剧场',
      source: '学生会',
      description:
        '初赛采取现场演唱形式，每人限时 4 分钟，自备伴奏。晋级选手将进入决赛并有机会登上校庆晚会舞台。',
    },
    {
      id: 'a5',
      name: '秋季校园双选会企业宣讲',
      type: '招聘宣讲',
      activityTime: at(20, 14, 0),
      deadline: at(14, 17, 0),
      location: '体育馆一层',
      source: '就业指导中心',
      description:
        '共 80 余家企业参会，涵盖互联网、制造、金融等行业，提供实习与校招岗位。请提前上传简历，现场可进行一对一面试。',
    },
    {
      id: 'a6',
      name: '“挑战杯”创业计划书竞赛',
      type: '竞赛',
      activityTime: at(-1, 14, 0),
      deadline: at(-3, 23, 59),
      location: '创新创业学院 B 座',
      source: '创新创业学院',
      description: '以团队形式提交创业计划书，评审通过后进入路演答辩环节，本次报名已结束。',
    },
    {
      id: 'a7',
      name: '心理健康周主题讲座',
      type: '讲座',
      activityTime: at(-5, 15, 0),
      deadline: at(-8, 12, 0),
      location: '学生活动中心 201',
      source: '心理健康中心',
      description: '围绕压力管理与情绪调节展开，已结束，可关注后续同类讲座。',
    },
  ]
}