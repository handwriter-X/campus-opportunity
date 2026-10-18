/// <reference types="@tarojs/taro" />

declare module '*.png'
declare module '*.jpg'
declare module '*.svg'

declare namespace NodeJS {
  interface ProcessEnv {
    TARO_ENV: 'weapp' | 'swan' | 'alipay' | 'h5' | 'rn' | 'tt' | 'qq' | 'jd' | 'quickapp'
    TARO_APP_AGENT_BASE_URL?: string
    TARO_APP_AGENT_API_ID?: string
    TARO_APP_AGENT_API_KEY?: string
  }
}