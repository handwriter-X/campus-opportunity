/**
 * Agent 接口统一配置
 * 优先读取 .env.* 中以 TARO_APP_ 开头的变量，未配置则使用下方占位符。
 *
 * ⚠️ 安全提醒：小程序包内的任何字符串都可以被反编译提取。
 * 生产环境强烈建议：前端只请求自己的后端网关（BFF），由网关持有真实 API Key 再转发给 Agent。
 * 此时 baseUrl 指向网关，apiKey 可换成短期 token。
 */
export const AGENT_CONFIG = {
  /** Agent 服务域名（需在飞书开放平台「网络请求域名」白名单中配置） */
  baseUrl: process.env.TARO_APP_AGENT_BASE_URL || 'https://your-agent-host.example.com',

  /** 👇 在这里填写 Agent API ID */
  apiId: process.env.TARO_APP_AGENT_API_ID || 'YOUR_AGENT_API_ID',

  /** 👇 在这里填写 Agent API Key */
  apiKey: process.env.TARO_APP_AGENT_API_KEY || 'YOUR_AGENT_API_KEY',

  /** 请求超时（ms） */
  timeout: 15000,

  /** 接口路径，按你的后端实际定义修改 */
     endpoints: {
    activityList: '/v1/activities/list',
    teamList: '/v1/teams/list',       // 组队需求列表
    teamDetail: '/v1/teams/detail',   // 组队需求详情（点击卡片时请求）
    teamApply: '/v1/teams/apply',     // 提交申请 → 后端让机器人通知发布者
    opportunityDetail: '/v1/opportunities/detail',
    action: '/v1/opportunities/action',
    chat: '/v1/agent/chat',
  },
} as const

/** 是否已填写真实配置（未填写时 services 会自动使用 mock 数据，方便先看 UI） */
export const isAgentConfigured =
  !AGENT_CONFIG.apiId.startsWith('YOUR_') &&
  !AGENT_CONFIG.apiKey.startsWith('YOUR_') &&
  !AGENT_CONFIG.baseUrl.includes('example.com')