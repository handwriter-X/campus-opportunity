import { useCallback, useMemo, useState } from 'react'
import { View, Text, Input, Picker, ScrollView, Textarea } from '@tarojs/components'
import Taro, { useLoad, usePullDownRefresh } from '@tarojs/taro'
import { isAgentConfigured } from '@/config/agent'
import Pill from '@/components/Pill'
import { applyTeam, getTeamDetail, getTeamRequests, mergeTeam } from '@/services/team'
import { sortByDeadlineProximity, withTeamStatus } from '@/utils/team'
import { getFeishuLoginCode } from '@/utils/feishu'
import type { TeamRequest, TeamStatus, TeamWithStatus } from '@/types/team'

/* ---------- 搜索条件 ---------- */
const STATUS_OPTIONS = ['全部状态', '仍在招募', '需求结束']

interface Filters {
  keyword: string
  statusIdx: number
}

/** 默认只显示「仍在招募」 */
const DEFAULT_FILTERS: Filters = { keyword: '', statusIdx: 1 }

const STATUS_STYLE: Record<TeamStatus, string> = {
  仍在招募: 'bg-green-500 text-white',
  需求结束: 'bg-gray-300 text-white',
}

/* ---------- 信息行（卡片用，紧凑） ---------- */
function CompactRow({ label, value }: { label: string; value: string }) {
  return (
    <View className="flex" style={{ marginTop: '6rpx' }}>
      <Text style={{ width: '128rpx', flexShrink: 0, fontSize: '22rpx', color: '#9ca3af' }}>{label}</Text>
      <Text className="flex-1" style={{ fontSize: '22rpx', color: '#374151' }}>
        {value}
      </Text>
    </View>
  )
}

/* ---------- 信息行（弹窗用） ---------- */
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

/* ---------- 人数胶囊 ---------- */
function CountPills({ t, height, fontSize, paddingX }: { t: TeamRequest; height: number; fontSize: number; paddingX: number }) {
  return (
    <View style={{ display: 'flex', flexDirection: 'row' }}>
      <Pill text={`已集结${t.currentCount}人`} className="bg-blue-50 text-blue-600" height={height} fontSize={fontSize} paddingX={paddingX} />
      <View style={{ width: '12rpx' }} />
      <Pill text={`需要招募${t.recruitCount}人`} className="bg-orange-50 text-orange-600" height={height} fontSize={fontSize} paddingX={paddingX} />
    </View>
  )
}

export default function TeamPage() {
  const [items, setItems] = useState<TeamRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [draft, setDraft] = useState<Filters>(DEFAULT_FILTERS)
  const [applied, setApplied] = useState<Filters>(DEFAULT_FILTERS)

  const [selected, setSelected] = useState<TeamWithStatus | null>(null)
  const [note, setNote] = useState('')
  const [applying, setApplying] = useState(false)
  const [appliedIds, setAppliedIds] = useState<string[]>([])

  const load = useCallback(async () => {
    try {
      setError('')
      setItems(await getTeamRequests())
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

  /** 过滤 + 排序 */
  const list = useMemo(() => {
    const now = Date.now()
    const kw = applied.keyword.trim().toLowerCase()

    // 直接输入「仍在招募」/「需求结束」，视为按状态搜索
    const kwStatus = STATUS_OPTIONS.slice(1).find((s) => s === kw)
    const statusWanted = kwStatus ?? (applied.statusIdx > 0 ? STATUS_OPTIONS[applied.statusIdx] : null)
    const terms = kwStatus ? [] : kw.split(/\s+/).filter(Boolean)

    const filtered = withTeamStatus(items, now).filter((t) => {
      if (statusWanted && t.status !== statusWanted) return false
      if (terms.length === 0) return true
      // 项目名称 + 招募角色 + 全部详情字段，多个关键词需同时命中
      const hay = [t.name, t.roles, t.description, t.requirements, t.duration, t.publisherName]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return terms.every((x) => hay.includes(x))
    })
    return sortByDeadlineProximity(filtered, now)
  }, [items, applied])

  const handleSearch = () => setApplied({ ...draft })
  const handleReset = () => {
    setDraft(DEFAULT_FILTERS)
    setApplied(DEFAULT_FILTERS)
  }

  /** 打开弹窗：先用列表数据立即展示，再请求详情接口补全 */
  const openDetail = async (t: TeamWithStatus) => {
    setSelected(t)
    setNote('')
    try {
      const d = await getTeamDetail(t.id)
      if (d) {
        setSelected((prev) => (prev && prev.id === t.id ? mergeTeam(prev, { ...d, closed: undefined } as any) : prev))
      }
    } catch (e) {
      console.warn('[team] 详情加载失败，使用列表数据', e)
    }
  }

  const handleApply = async () => {
    if (!selected || applying) return
    setApplying(true)
    try {
      const userCode = await getFeishuLoginCode()
      const res = await applyTeam({ teamId: selected.id, message: note.trim(), userCode })
      setAppliedIds((prev) => [...prev, selected.id])
      Taro.showToast({ title: res.message || '申请已发送', icon: 'success' })
    } catch (e) {
      Taro.showToast({ title: (e as Error).message || '申请失败', icon: 'none' })
    } finally {
      setApplying(false)
    }
  }

  /* ---------- 加载 / 错误 ---------- */
  if (loading) {
    return (
      <View className="flex items-center justify-center h-screen">
        <Text className="text-sm text-gray-400">正在加载组队需求…</Text>
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

  const hasApplied = selected ? appliedIds.includes(selected.id) : false
  const selectedEnded = selected?.status === '需求结束'

  return (
    <View className="min-h-screen pb-8">
      {!isAgentConfigured && (
        <View className="px-4 py-1 bg-yellow-50">
          <Text style={{ fontSize: '20rpx' }} className="text-yellow-700">
            当前为 Mock 数据：请在 src/config/agent.ts 或 .env 中填写 Agent API ID / Key
          </Text>
        </View>
      )}

      {/* ====== 顶部搜索栏 ====== */}
      <View
        className="px-4 bg-white shadow-sm"
        style={{ position: 'sticky', top: 0, zIndex: 10, paddingTop: '16rpx', paddingBottom: '16rpx' }}
      >
        <View className="px-3 rounded-full bg-gray-100" style={{ paddingTop: '10rpx', paddingBottom: '10rpx' }}>
          <Input
            style={{ fontSize: '24rpx' }}
            value={draft.keyword}
            placeholder="搜索项目名称、招募角色或需求内容"
            confirmType="search"
            onInput={(e) => setDraft({ ...draft, keyword: e.detail.value })}
            onConfirm={handleSearch}
          />
        </View>

        <View className="flex items-center" style={{ marginTop: '12rpx' }}>
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
          <View className="flex-1" />
          <View
            className="mr-2 text-center rounded-full bg-gray-100"
            style={{ padding: '8rpx 40rpx' }}
            onClick={handleReset}
          >
            <Text style={{ fontSize: '24rpx', color: '#4b5563' }}>重置</Text>
          </View>
          <View
            className="text-center rounded-full bg-blue-500"
            style={{ padding: '8rpx 40rpx' }}
            onClick={handleSearch}
          >
            <Text style={{ fontSize: '24rpx', color: '#ffffff' }}>查询</Text>
          </View>
        </View>
      </View>

      {/* ====== 组队需求卡片列表 ====== */}
      <View className="px-4" style={{ marginTop: '16rpx' }}>
        {list.length === 0 && (
          <View className="flex items-center justify-center py-20">
            <Text className="text-sm text-gray-400">没有符合条件的组队需求</Text>
          </View>
        )}

        {list.map((t) => (
          <View
            key={t.id}
            className={`bg-white shadow-sm ${t.status === '需求结束' ? 'opacity-70' : ''}`}
            style={{ marginBottom: '16rpx', padding: '20rpx 24rpx', borderRadius: '24rpx' }}
            onClick={() => openDetail(t)}
          >
            {/* 项目名称 + 需求状态 */}
            <View className="flex items-start justify-between">
              <View className="flex-1 pr-2">
                <Text className="block font-semibold" style={{ fontSize: '28rpx', lineHeight: '38rpx' }}>
                  {t.name}
                </Text>
              </View>
              <Pill text={t.status} className={STATUS_STYLE[t.status]} height={36} fontSize={20} paddingX={18} />
            </View>

            {/* 已集结 / 需要招募 */}
            <View style={{ marginTop: '8rpx' }}>
              <CountPills t={t} height={34} fontSize={20} paddingX={16} />
            </View>

            <CompactRow label="招募角色" value={t.roles} />
            <CompactRow label="截止时间" value={t.deadline} />
          </View>
        ))}
      </View>

      {/* ====== 详情弹窗 ====== */}
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
            <View className="flex items-center justify-between px-5 pt-5 pb-3">
              <Text className="text-base font-bold">组队需求详情</Text>
              <View className="px-3 py-1" onClick={() => setSelected(null)}>
                <Text className="text-sm text-gray-400">关闭</Text>
              </View>
            </View>

            <ScrollView scrollY style={{ maxHeight: '58vh' }}>
              <View className="px-5 pb-4">
                <View className="flex items-start justify-between">
                  <View className="flex-1 pr-3">
                    <Text className="block text-lg font-semibold leading-snug">{selected.name}</Text>
                  </View>
                  <Pill text={selected.status} className={STATUS_STYLE[selected.status]} height={44} fontSize={24} paddingX={22} />
                </View>

                <View style={{ marginTop: '12rpx' }}>
                  <CountPills t={selected} height={40} fontSize={24} paddingX={20} />
                </View>

                <InfoRow label="招募角色" value={selected.roles} />
                <InfoRow label="截止时间" value={selected.deadline} />
                {selected.duration && <InfoRow label="预计周期" value={selected.duration} />}
                {selected.publisherName && <InfoRow label="发布者" value={selected.publisherName} />}
                {selected.publishTime && <InfoRow label="发布时间" value={selected.publishTime} />}

                {selected.description && (
                  <View className="mt-4 p-4 rounded-xl bg-gray-50">
                    <Text className="block text-sm font-semibold text-gray-800">项目介绍</Text>
                    <Text className="block mt-2 text-sm text-gray-600 leading-relaxed">{selected.description}</Text>
                  </View>
                )}

                {selected.requirements && (
                  <View className="mt-3 p-4 rounded-xl bg-gray-50">
                    <Text className="block text-sm font-semibold text-gray-800">能力 / 经验要求</Text>
                    <Text className="block mt-2 text-sm text-gray-600 leading-relaxed">{selected.requirements}</Text>
                  </View>
                )}

                {!selectedEnded && !hasApplied && (
                  <View className="mt-3">
                    <Text className="block text-sm font-semibold text-gray-800">申请留言（选填）</Text>
                    <View className="mt-2 p-3 rounded-xl bg-gray-100">
                      <Textarea
                        style={{ width: '100%', height: '140rpx', fontSize: '26rpx' }}
                        value={note}
                        maxlength={200}
                        placeholder="简单介绍自己，并留下联系方式，方便发布者联系你"
                        onInput={(e) => setNote(e.detail.value)}
                      />
                    </View>
                  </View>
                )}
              </View>
            </ScrollView>

            {/* 底部「申请」按钮 */}
            <View className="px-5 pt-3" style={{ paddingBottom: '40rpx' }}>
              <View
                className={`text-center rounded-full ${
                  selectedEnded || hasApplied ? 'bg-gray-300' : applying ? 'bg-blue-300' : 'bg-blue-500'
                }`}
                style={{ padding: '22rpx 0' }}
                onClick={selectedEnded || hasApplied ? undefined : handleApply}
              >
                <Text style={{ fontSize: '30rpx', color: '#ffffff' }}>
                  {selectedEnded ? '需求已结束' : hasApplied ? '已申请' : applying ? '发送中…' : '申请'}
                </Text>
              </View>
            </View>
          </View>
        </View>
      )}
    </View>
  )
}