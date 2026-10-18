import Taro from '@tarojs/taro'

/** 获取飞书登录 code，后端可用它换取用户身份（免登） */
export async function getFeishuLoginCode(): Promise<string | undefined> {
  try {
    const { code } = await Taro.login()
    return code
  } catch (e) {
    console.warn('[feishu] login failed', e)
    return undefined
  }
}