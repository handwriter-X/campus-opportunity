// 抢先定义并阻止 _raf 报错
if (typeof globalThis !== 'undefined') {
  // @ts-ignore
  globalThis._raf = function(cb: any) { return setTimeout(cb, 16); };
}
// @ts-ignore
if (typeof window !== 'undefined') {
  // @ts-ignore
  window._raf = function(cb: any) { return setTimeout(cb, 16); };
}

import { Component, PropsWithChildren } from 'react'
import './app.scss'

class App extends Component<PropsWithChildren> {
  componentDidMount () {}
  componentDidShow () {}
  componentDidHide () {}

  render () {
    return this.props.children
  }
}

export default App