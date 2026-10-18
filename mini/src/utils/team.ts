import { parseTime } from '@/utils/activity'
import type { TeamRequest, TeamWithStatus } from '@/types/team'

/** 状态：后端标记结束，或已超过截止时间 → 需求结束 */
export function withTeamStatus(list: TeamRequest[], now = Date.now()): TeamWithStatus[] {
  return list.map((t) => ({
    ...t,
    status: t.closed || now > parseTime(t.deadline) ? '需求结束' : '仍在招募',
  }))
}

/** 按截止时间距离现在由近到远排序（最近截止的在最上面） */
export function sortByDeadlineProximity<T extends TeamRequest>(list: T[], now = Date.now()): T[] {
  return [...list].sort((a, b) => {
    const ta = parseTime(a.deadline)
    const tb = parseTime(b.deadline)
    // 没有截止时间（长期有效）的排在最后，别让 NaN 打乱顺序
    if (isNaN(ta) && isNaN(tb)) return 0
    if (isNaN(ta)) return 1
    if (isNaN(tb)) return -1
    return Math.abs(ta - now) - Math.abs(tb - now)
  })
}