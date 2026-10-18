import { AGENT_CONFIG, isAgentConfigured } from '@/config/agent'
import type { TeamApplyPayload, TeamApplyResult, TeamRequest } from '@/types/team'
import { agentRequest } from './request'
import { normalizeTime, pick } from './agent'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const pad = (n: number) => ('0' + n).slice(-2)

/* ====================== 真实接口 ====================== */

/** 组队需求列表 */
export async function getTeamRequests(): Promise<TeamRequest[]> {
  if (!isAgentConfigured) {
    await sleep(400)
    return mockTeams()
  }
  const raw = await agentRequest<unknown>(AGENT_CONFIG.endpoints.teamList, { data: {} })
  const arr: unknown[] = Array.isArray(raw)
    ? raw
    : ((raw as any)?.list ?? (raw as any)?.items ?? (raw as any)?.teams ?? [])
  return arr.map(normalizeTeam).filter((t): t is TeamRequest => t !== null)
}

/** 组队需求详情（后端 Agent 整合后的信息） */
export async function getTeamDetail(id: string): Promise<TeamRequest | null> {
  if (!isAgentConfigured) {
    await sleep(200)
    return mockTeams().find((t) => t.id === id) ?? null
  }
  const raw = await agentRequest<unknown>(AGENT_CONFIG.endpoints.teamDetail, { data: { id } })
  return normalizeTeam(raw, 0)
}

/** 提交申请：后端收到后通过飞书机器人私信发布者 */
export async function applyTeam(payload: TeamApplyPayload): Promise<TeamApplyResult> {
  if (!isAgentConfigured) {
    await sleep(700)
    return { message: '申请已发送' }
  }
  return agentRequest<TeamApplyResult>(AGENT_CONFIG.endpoints.teamApply, { data: { ...payload } })
}

/** 把详情里有值的字段合并进列表项（空值不覆盖） */
export function mergeTeam<T extends TeamRequest>(base: T, extra: Partial<TeamRequest>): T {
  const out: any = { ...base }
  Object.keys(extra).forEach((k) => {
    const v = (extra as any)[k]
    if (v !== undefined && v !== '') out[k] = v
  })
  return out
}

/* ====================== 数据适配层 ======================
 * 后端字段名不同时，只改下面的别名列表。
 */
function normalizeTeam(raw: unknown, idx: number): TeamRequest | null {
  const o: any = raw
  const name = pick(o, ['name', 'title', 'projectName', 'project_name'])
  const deadline = normalizeTime(
    pick(o, ['deadline', 'recruitDeadline', 'recruit_deadline', 'endTime', 'end_time']),
  )
  // ⚠️ 只要求名称。**截止时间可以没有** —— 组队需求本来就不一定设截止，
  // 我们的【组队需求】表里也没有这个字段。缺了就当作「长期有效」，
  // 千万别整条丢掉（否则真实需求一条都显示不出来）。
  if (!name) {
    console.warn('[team] 丢弃无效组队需求（缺少项目名称）:', raw)
    return null
  }

  const toNum = (v: unknown) => {
    const n = Number(v)
    return isNaN(n) ? 0 : n
  }
  const str = (keys: string[]) => {
    const v = pick(o, keys)
    return v === undefined ? undefined : String(v)
  }

  const rolesRaw = pick(o, ['roles', 'role', 'recruitRoles', 'recruit_roles', 'positions'])
  const roles = Array.isArray(rolesRaw) ? rolesRaw.map(String).join('、') : String(rolesRaw ?? '待定')

  const statusRaw = String(pick(o, ['status', 'state']) ?? '')
  const closed =
    /结束|关闭|closed|ended|finished/i.test(statusRaw) || pick(o, ['closed', 'isClosed']) === true

  return {
    id: String(pick(o, ['id', 'teamId', 'team_id', 'uuid']) ?? `team-${idx}`),
    name: String(name),
    currentCount: toNum(pick(o, ['currentCount', 'current_count', 'memberCount', 'member_count'])),
    recruitCount: toNum(pick(o, ['recruitCount', 'recruit_count', 'needCount', 'need_count'])),
    roles,
    deadline,
    closed,
    description: str(['description', 'desc', 'intro', 'content', 'summary']),
    requirements: str(['requirements', 'requirement', 'skills', 'demand']),
    duration: str(['duration', 'period', 'projectPeriod']),
    publisherName: str(['publisherName', 'publisher_name', 'publisher', 'owner', 'ownerName']),
    publishTime: normalizeTime(pick(o, ['publishTime', 'publish_time', 'createdAt', 'created_at']), '00:00') || undefined,
  }
}

/* ====================== mock ====================== */

function at(offsetDays: number, hour = 18, minute = 0): string {
  const d = new Date()
  d.setDate(d.getDate() + offsetDays)
  d.setHours(hour, minute, 0, 0)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function mockTeams(): TeamRequest[] {
  return [
    {
      id: 't1',
      name: '校园二手交易小程序',
      currentCount: 3,
      recruitCount: 2,
      roles: '前端设计、UI 设计',
      deadline: at(2, 23, 59),
      closed: false,
      description:
        '做一个面向本校学生的二手物品交易小程序，已完成需求文档和后端接口，目前缺少界面设计与前端实现。计划参加本学期的互联网+创新创业大赛。',
      requirements: '熟悉 Figma 或 React 之一；有小程序开发经验优先；每周可投入 6 小时以上。',
      duration: '约 3 个月',
      publisherName: '张同学（计算机学院）',
      publishTime: at(-2, 10, 0),
    },
    {
      id: 't2',
      name: '数学建模国赛备战队',
      currentCount: 2,
      recruitCount: 1,
      roles: '算法建模、论文写作',
      deadline: at(5, 12, 0),
      closed: false,
      description: '备战全国大学生数学建模竞赛，已有 2 名队员，缺 1 名负责建模与论文的同学，赛前会定期集训。',
      requirements: '会使用 Python 或 MATLAB；有建模比赛经历优先；英语文献阅读能力良好。',
      duration: '赛前 2 个月集训 + 比赛 3 天',
      publisherName: '李同学（理学院）',
      publishTime: at(-4, 9, 30),
    },
    {
      id: 't3',
      name: '乡村支教短视频纪录片',
      currentCount: 4,
      recruitCount: 3,
      roles: '摄影摄像、剪辑、文案策划',
      deadline: at(9, 18, 0),
      closed: false,
      description: '暑期支教项目的纪录片制作，记录乡村学校与志愿者的故事，成片将在校内公众号和短视频平台发布。',
      requirements: '有拍摄或剪辑作品者优先，需自带设备或可借用学院器材；能参与线下拍摄。',
      duration: '约 2 个月',
      publisherName: '王同学（新闻传播学院）',
      publishTime: at(-1, 15, 0),
    },
    {
      id: 't4',
      name: '智能垃圾分类设备原型',
      currentCount: 3,
      recruitCount: 2,
      roles: '嵌入式开发、结构设计',
      deadline: at(14, 20, 0),
      closed: false,
      description: '基于图像识别的垃圾分类投放设备，已有算法模块，需要硬件和结构方面的同学完成原型搭建与测试。',
      requirements: '熟悉 STM32 或树莓派；会 SolidWorks 等建模软件；愿意利用周末到实验室。',
      duration: '约 4 个月',
      publisherName: '赵同学（电子信息学院）',
      publishTime: at(-3, 20, 0),
    },
    {
      id: 't5',
      name: '校园社团联合音乐节策划',
      currentCount: 5,
      recruitCount: 2,
      roles: '活动运营、赞助拉取',
      deadline: at(-2, 18, 0),
      closed: false,
      description: '联合多个音乐类社团举办校园音乐节，本次招募已经结束，感谢关注。',
      requirements: '沟通能力强，有活动组织经验。',
      duration: '约 1 个月',
      publisherName: '陈同学（学生会）',
      publishTime: at(-12, 10, 0),
    },
    {
      id: 't6',
      name: '“挑战杯”红色专项项目组',
      currentCount: 4,
      recruitCount: 1,
      roles: '数据分析',
      deadline: at(7, 12, 0),
      closed: true,
      description: '该需求已由发布者提前关闭招募。',
      requirements: '—',
      duration: '约 5 个月',
      publisherName: '刘同学（马克思主义学院）',
      publishTime: at(-10, 10, 0),
    },
  ]
}