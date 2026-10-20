import React from 'react'
import ReactDOM from 'react-dom/client'
import 'antd/dist/reset.css'
import './styles.css'
import App from './App'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

// 装到手机主屏幕后由这份缓存接管静态文件，断网时至少还能看到界面。
// 浏览器只在 HTTPS 和 localhost 下允许注册，所以在局域网 http 上会静默跳过——
// 这里用 catch 吞掉，不要因为注册不上就在控制台里报错吓人。
if (!import.meta.env.DEV && 'serviceWorker' in navigator) {
  const secure = window.location.protocol === 'https:'
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)
  if (secure || loopback) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('./sw.js').catch(() => {})
    })
  }
}
