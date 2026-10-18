import type { Activity, ActivityWithStatus } from '@/types/activity'

/** 兼容 iOS：把 "YYYY-MM-DD HH:mm" 转成 "YYYY/MM/DD HH:mm" 再解析 */
export const parseTime = (s: string): number => new Date(s.replace(/-/g, '/')).getTime()

/** 根据当前时间和截止时间计算状态 */
export function withStatus(list: Activity[], now = Date.now()): ActivityWithStatus[] {
  return list.map((a) => ({
    ...a,
    status: now > parseTime(a.deadline) ? '已截止' : '可参与',
  }))
}

/** 按「报名截止时间距离现在由近到远」排序：
 *  可参与的活动 → 最快截止的在最上面；已截止的活动 → 刚截止的在前面 */
export function sortByDeadlineProximity<T extends Activity>(list: T[], now = Date.now()): T[] {
  return [...list].sort((a, b) => {
    const ta = parseTime(a.deadline)
    const tb = parseTime(b.deadline)
    // 没有截止时间的排最后，别让 NaN 打乱顺序
    if (isNaN(ta) && isNaN(tb)) return 0
    if (isNaN(ta)) return 1
    if (isNaN(tb)) return -1
    return Math.abs(ta - now) - Math.abs(tb - now)
  })
}