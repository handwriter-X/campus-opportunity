// 完美复刻并安全接管 Taro 运行时的 requestAnimationFrame，防止 _raf 未初始化报错
export * from '@tarojs/runtime'

// 安全重写全局的 rAF 避免报错
if (typeof window !== 'undefined') {
  // @ts-ignore
  window.requestAnimationFrame = window.requestAnimationFrame || function(cb: any) { return setTimeout(cb, 16); };
}