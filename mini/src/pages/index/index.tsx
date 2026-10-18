import { useCallback, useMemo, useState } from 'react'
import { View, Text, Input, Picker, ScrollView } from '@tarojs/components'
import Taro, { useLoad, usePullDownRefresh } from '@tarojs/taro'
import { isAgentConfigured } from '@/config/agent'
import { getActivities } from '@/services/agent'
import { parseTime, sortByDeadlineProximity, withStatus } from '@/utils/activity'
import type { Activity, ActivityStatus, ActivityWithStatus } from '@/types/activity'

/* ---------- 搜索条件 ---------- */
const TYPE_OPTIONS = ['全部类型', '竞赛', '讲座', '志愿实践', '文体活动', '招聘宣讲']
const STATUS_OPTIONS = ['全部状态', '可参与', '已截止']

interface Filters {
  keyword: string
  typeIdx: number
  statusIdx: number
  /** 报名截止日期上限，格式 YYYY-MM-DD，空表示不限 */
  deadline: string
}

/** 默认只显示「可参与」 */
const DEFAULT_FILTERS: Filters = { keyword: '', typeIdx: 0, statusIdx: 1, deadline: '' }

/* ---------- 样式映射 ---------- */
const TYPE_STYLE: Record<string, string> = {
  竞赛: 'bg-orange-50 text-orange-600',
  讲座: 'bg-blue-50 text-blue-600',
  志愿实践: 'bg-green-50 text-green-600',
  文体活动: 'bg-purple-50 text-purple-600',
  招聘宣讲: 'bg-cyan-50 text-cyan-600',
}
const typeCls = (t: string) => TYPE_STYLE[t] || 'bg-gray-100 text-gray-600'

const STATUS_STYLE: Record<ActivityStatus, string> = {
  可参与: 'bg-green-500 text-white',
  已截止: 'bg-gray-300 text-white',
}

/* ---------- 小组件：胶囊标签（状态 / 类型），文字严格居中 ---------- */
function Pill({
  text,
  className = '',
  height = 36,
  fontSize = 20,
  paddingX = 16,
}: {
  text: string
  className?: string
  height?: number
  fontSize?: number
  paddingX?: number
}) {
  return (
    <View
      className={className}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        height: `${height}rpx`,
        padding: `0 ${paddingX}rpx`,
        borderRadius: `${height / 2}rpx`,
      }}
    >
      <Text style={{ fontSize: `${fontSize}rpx`, lineHeight: `${height}rpx`, height: `${height}rpx` }}>
        {text}
      </Text>
    </View>
  )
}

/* ---------- 小组件：信息行（紧凑版，用于卡片） ---------- */
function CompactRow({ label, value }: { label: string; value: string }) {
  return (
    <View className="flex" style={{ marginTop: '6rpx' }}>
      <Text style={{ width: '128rpx', flexShrink: 0, fontSize: '22rpx', color: '#9ca3af' }}>
        {label}
      </Text>
      <Text className="flex-1" style={{ fontSize: '22rpx', color: '#374151' }}>
        {value}
      </Text>
    </View>
  )
}

/* ---------- 小组件：信息行（标准版，用于详情弹窗） ---------- */
function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <View className="flex mt-2">
      <Text style={{ width: '160rpx', flexShrink: 0 }} className="text-sm text-gray-400">
        {label}
      </Text>
      <Text className="flex-1 text-sm text-gray-700">{value}</Text>
    </View>
  )
}

export default function Index() {
  const [activities, setActivities] = useState<Activity[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // draft：输入框里正在编辑的条件；applied：点击「查询」后真正生效的条件
  const [draft, setDraft] = useState<Filters>(DEFAULT_FILTERS)
  const [applied, setApplied] = useState<Filters>(DEFAULT_FILTERS)

  const [selected, setSelected] = useState<ActivityWithStatus | null>(null)

  const load = useCallback(async () => {
    try {
      setError('')
      setActivities(await getActivities())
    } catch (e) {
      setError((e as Error).message || '加载失败，请稍后重试')
    } finally {
      setLoading(false)
      Taro.stopPullDownRefresh()
    }
  }, [])

  useLoad(() => {
    load()
  })

  usePullDownRefresh(() => {
    load()
  })

  /** 过滤 + 排序（仅在数据或「已生效条件」变化时重算） */
  const list = useMemo(() => {
    const now = Date.now()
    const { keyword, typeIdx, statusIdx, deadline } = applied
    const kw = keyword.trim().toLowerCase()
    const deadlineLimit = deadline ? parseTime(`${deadline} 23:59`) : null

    const filtered = withStatus(activities, now).filter((a) => {
      if (kw && !a.name.toLowerCase().includes(kw)) return false
      if (typeIdx > 0 && a.type !== TYPE_OPTIONS[typeIdx]) return false
      if (statusIdx > 0 && a.status !== STATUS_OPTIONS[statusIdx]) return false
      if (deadlineLimit !== null && parseTime(a.deadline) > deadlineLimit) return false
      return true
    })
    return sortByDeadlineProximity(filtered, now)
  }, [activities, applied])

  const handleSearch = () => setApplied({ ...draft })

  const handleReset = () => {
    setDraft(DEFAULT_FILTERS)
    setApplied(DEFAULT_FILTERS)
  }

  /* ---------- 加载 / 错误状态 ---------- */
  if (loading) {
    return (
      <View className="flex items-center justify-center h-screen">
        <Text className="text-sm text-gray-400">正在加载活动…</Text>
      </View>
    )
  }

  if (error) {
    return (
      <View className="flex flex-col items-center justify-center h-screen px-8">
        <Text className="text-base text-gray-600 mb-4">{error}</Text>
        <View className="px-6 py-2 rounded-full bg-blue-500" onClick={load}>
          <Text className="text-sm text-white">重新加载</Text>
        </View>
      </View>
    )
  }

  return (
    <View className="min-h-screen pb-8">
      {!isAgentConfigured && (
        <View className="px-4 py-1 bg-yellow-50">
          <Text style={{ fontSize: '20rpx' }} className="text-yellow-700">
            当前为 Mock 数据：请在 src/config/agent.ts 或 .env 中填写 Agent API ID / Key
          </Text>
        </View>
      )}

      {/* ====== 顶部搜索栏（紧凑版） ====== */}
      <View
        className="px-4 bg-white shadow-sm"
        style={{ position: 'sticky', top: 0, zIndex: 10, paddingTop: '16rpx', paddingBottom: '16rpx' }}
      >
        {/* 活动名称 */}
        <View className="px-3 rounded-full bg-gray-100" style={{ paddingTop: '10rpx', paddingBottom: '10rpx' }}>
          <Input
            style={{ fontSize: '24rpx' }}
            value={draft.keyword}
            placeholder="搜索活动名称"
            confirmType="search"
            onInput={(e) => setDraft({ ...draft, keyword: e.detail.value })}
            onConfirm={handleSearch}
          />
        </View>

        {/* 活动类型 / 状态 / 报名截止时间 */}
        <View className="flex" style={{ marginTop: '12rpx' }}>
          <Picker
            mode="selector"
            range={TYPE_OPTIONS}
            value={draft.typeIdx}
            onChange={(e) => setDraft({ ...draft, typeIdx: Number(e.detail.value) })}
          >
            <View className="px-2 mr-2 rounded-full bg-gray-100" style={{ paddingTop: '6rpx', paddingBottom: '6rpx' }}>
              <Text style={{ fontSize: '22rpx', color: '#374151' }}>{TYPE_OPTIONS[draft.typeIdx]} ▾</Text>
            </View>
          </Picker>

          <Picker
            mode="selector"
            range={STATUS_OPTIONS}
            value={draft.statusIdx}
            onChange={(e) => setDraft({ ...draft, statusIdx: Number(e.detail.value) })}
          >
            <View className="px-2 mr-2 rounded-full bg-gray-100" style={{ paddingTop: '6rpx', paddingBottom: '6rpx' }}>
              <Text style={{ fontSize: '22rpx', color: '#374151' }}>{STATUS_OPTIONS[draft.statusIdx]} ▾</Text>
            </View>
          </Picker>

          <Picker
            mode="date"
            value={draft.deadline}
            onChange={(e) => setDraft({ ...draft, deadline: e.detail.value })}
          >
            <View className="px-2 rounded-full bg-gray-100" style={{ paddingTop: '6rpx', paddingBottom: '6rpx' }}>
              <Text style={{ fontSize: '22rpx', color: '#374151' }}>
                {draft.deadline ? `截止≤${draft.deadline}` : '报名截止日期 ▾'}
              </Text>
            </View>
          </Picker>
        </View>

        {/* 操作按钮 */}
        <View className="flex" style={{ marginTop: '12rpx' }}>
          <View
            className="flex-1 mr-2 text-center rounded-full bg-gray-100"
            style={{ paddingTop: '8rpx', paddingBottom: '8rpx' }}
            onClick={handleReset}
          >
            <Text style={{ fontSize: '24rpx', color: '#4b5563' }}>重置</Text>
          </View>
          <View
            className="flex-1 text-center rounded-full bg-blue-500"
            style={{ paddingTop: '8rpx', paddingBottom: '8rpx' }}
            onClick={handleSearch}
          >
            <Text style={{ fontSize: '24rpx', color: '#ffffff' }}>查询</Text>
          </View>
        </View>
      </View>

      {/* ====== 活动卡片列表（紧凑版：无「信息来源」） ====== */}
      <View className="px-4" style={{ marginTop: '16rpx' }}>
        {list.length === 0 && (
          <View className="flex items-center justify-center py-20">
            <Text className="text-sm text-gray-400">没有符合条件的活动</Text>
          </View>
        )}

        {list.map((a) => {
          const expired = a.status === '已截止'
          return (
            <View
              key={a.id}
              className={`bg-white shadow-sm ${expired ? 'opacity-70' : ''}`}
              style={{
                marginBottom: '16rpx',
                padding: '20rpx 24rpx',
                borderRadius: '24rpx',
              }}
              onClick={() => setSelected(a)}
            >
              {/* 活动名称 + 状态 */}
              <View className="flex items-start justify-between">
                <View className="flex-1 pr-2">
                  <Text className="block font-semibold" style={{ fontSize: '28rpx', lineHeight: '38rpx' }}>
                    {a.name}
                  </Text>
                </View>
                <Pill text={a.status} className={STATUS_STYLE[a.status]} height={36} fontSize={20} paddingX={18} />
              </View>

              {/* 活动类型 */}
              <View style={{ marginTop: '8rpx', display: 'flex', flexDirection: 'row' }}>
                <Pill text={a.type} className={typeCls(a.type)} height={34} fontSize={20} paddingX={16} />
              </View>

              <CompactRow label="活动时间" value={a.activityTime} />
              <CompactRow label="报名截止" value={a.deadline} />
              <CompactRow label="活动地点" value={a.location} />
            </View>
          )
        })}
      </View>

      {/* ====== 详情弹窗（完整七项信息 + 活动介绍） ====== */}
      {selected && (
        <View
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            zIndex: 100,
            backgroundColor: 'rgba(0,0,0,0.5)',
          }}
          onClick={() => setSelected(null)}
        >
          <View
            className="bg-white"
            style={{
              position: 'absolute',
              left: 0,
              right: 0,
              bottom: 0,
              borderTopLeftRadius: '32rpx',
              borderTopRightRadius: '32rpx',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* 弹窗标题栏 */}
            <View className="flex items-center justify-between px-5 pt-5 pb-3">
              <Text className="text-base font-bold">活动详情</Text>
              <View className="px-3 py-1" onClick={() => setSelected(null)}>
                <Text className="text-sm text-gray-400">关闭</Text>
              </View>
            </View>

            <ScrollView scrollY style={{ maxHeight: '70vh' }}>
              <View className="px-5 pb-4">
                <View className="flex items-start justify-between">
                  <View className="flex-1 pr-3">
                    <Text className="block text-lg font-semibold leading-snug">{selected.name}</Text>
                  </View>
                  <Pill
                    text={selected.status}
                    className={STATUS_STYLE[selected.status]}
                    height={44}
                    fontSize={24}
                    paddingX={22}
                  />
                </View>

                <View className="mt-2" style={{ display: 'flex', flexDirection: 'row' }}>
                  <Pill
                    text={selected.type}
                    className={typeCls(selected.type)}
                    height={40}
                    fontSize={24}
                    paddingX={20}
                  />
                </View>

                <InfoRow label="活动时间" value={selected.activityTime} />
                <InfoRow label="报名截止" value={selected.deadline} />
                <InfoRow label="活动地点" value={selected.location} />
                <InfoRow label="信息来源" value={selected.source} />

                {/* 活动介绍 */}
                <View className="mt-4 p-4 rounded-xl bg-gray-50">
                  <Text className="block text-sm font-semibold text-gray-800">活动介绍</Text>
                  <Text className="block mt-2 text-sm text-gray-600 leading-relaxed">
                    {selected.description}
                  </Text>
                </View>
              </View>
              <View style={{ height: '40rpx' }} />
            </ScrollView>
          </View>
        </View>
      )}
    </View>
  )
}