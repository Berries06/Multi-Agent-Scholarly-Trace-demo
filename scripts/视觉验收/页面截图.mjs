import { spawn } from 'node:child_process'
import { mkdir, rm, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'

const edge = process.env.YANHAI_EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const targetUrl = process.argv[2] || 'http://127.0.0.1:5173/'
const outputDir = path.resolve(process.argv[3] || '.runtime/视觉验收/当前')
const email = process.env.YANHAI_VISUAL_EMAIL || ''
const password = process.env.YANHAI_VISUAL_PASSWORD || ''
const triggerResearchRun = process.env.YANHAI_VISUAL_TRIGGER_RUN === '1'
const researchProviderText = process.env.YANHAI_VISUAL_PROVIDER_TEXT || ''
const progressDelay = Number(process.env.YANHAI_VISUAL_PROGRESS_DELAY || 2500)
const scrollToProgress = process.env.YANHAI_VISUAL_SCROLL_PROGRESS === '1'
const port = 9400 + Math.floor(Math.random() * 400)
const profile = path.join(os.tmpdir(), `yanhai-visual-${process.pid}-${Date.now()}`)

await mkdir(outputDir, { recursive: true })

const browser = spawn(edge, [
  '--headless=new',
  '--disable-gpu',
  '--hide-scrollbars',
  '--no-first-run',
  '--no-default-browser-check',
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`,
  'about:blank',
], { stdio: 'ignore', windowsHide: true })

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds))

async function browserWebSocketUrl() {
  const deadline = Date.now() + 15_000
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/version`)
      if (response.ok) return (await response.json()).webSocketDebuggerUrl
    } catch {}
    await delay(200)
  }
  throw new Error('Edge DevTools endpoint did not become ready')
}

class Cdp {
  constructor(url) {
    this.nextId = 1
    this.pending = new Map()
    this.socket = new WebSocket(url)
  }

  async open() {
    if (this.socket.readyState === WebSocket.OPEN) return
    await new Promise((resolve, reject) => {
      this.socket.addEventListener('open', resolve, { once: true })
      this.socket.addEventListener('error', reject, { once: true })
    })
  }

  send(method, params = {}, sessionId = undefined) {
    const id = this.nextId++
    const payload = { id, method, params }
    if (sessionId) payload.sessionId = sessionId
    const promise = new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }))
    this.socket.send(JSON.stringify(payload))
    return promise
  }

  listen() {
    this.socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data)
      if (!message.id || !this.pending.has(message.id)) return
      const { resolve, reject } = this.pending.get(message.id)
      this.pending.delete(message.id)
      if (message.error) reject(new Error(`${message.error.code}: ${message.error.message}`))
      else resolve(message.result)
    })
  }
}

let cdp
try {
  cdp = new Cdp(await browserWebSocketUrl())
  cdp.listen()
  await cdp.open()
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' })
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true })
  await cdp.send('Page.enable', {}, sessionId)
  await cdp.send('Runtime.enable', {}, sessionId)
  await cdp.send('Network.enable', {}, sessionId)
  await cdp.send('Page.navigate', { url: targetUrl }, sessionId)
  await delay(3500)

  if (email && password) {
    const loginUrl = new URL('api/auth/login', targetUrl).href
    const expression = `fetch(${JSON.stringify(loginUrl)}, {
      method: 'POST',
      credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(${JSON.stringify({ identifier: email, password })})
    }).then(async response => ({ok: response.ok, status: response.status, body: await response.json()}))`
    const login = await cdp.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    }, sessionId)
    if (!login.result?.value?.ok) throw new Error(`Login failed: ${JSON.stringify(login.result?.value)}`)
  }

  const requestedViewports = new Set((process.env.YANHAI_VISUAL_VIEWPORTS || '').split(',').filter(Boolean))
  const requestedWorkspaces = new Set((process.env.YANHAI_VISUAL_WORKSPACES || '').split(',').filter(Boolean))
  const viewports = [
    { name: 'desktop', width: 1440, height: 1000, mobile: false },
    { name: 'tablet', width: 1024, height: 900, mobile: false },
    { name: 'mobile', width: 390, height: 844, mobile: true },
  ].filter((item) => requestedViewports.size === 0 || requestedViewports.has(item.name))
  const workspaces = (email && password
    ? [
        { name: 'product', index: 0 },
        { name: 'ingestion', index: 1 },
        { name: 'atlas', index: 2 },
        { name: 'experiments', index: 3 },
      ]
    : [{ name: 'login', index: -1 }])
    .filter((item) => requestedWorkspaces.size === 0 || requestedWorkspaces.has(item.name))
  const report = []

  for (const viewport of viewports) {
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: viewport.width,
      height: viewport.height,
      deviceScaleFactor: 1,
      mobile: viewport.mobile,
    }, sessionId)
    await cdp.send('Page.reload', { ignoreCache: true }, sessionId)
    await delay(3500)
    for (const workspace of workspaces) {
      if (workspace.index >= 0) {
        const selected = await cdp.send('Runtime.evaluate', {
          expression: `(() => {
            const button = document.querySelectorAll('.workspace-nav button')[${workspace.index}];
            if (!button) return false;
            button.click();
            return true;
          })()`,
          returnByValue: true,
        }, sessionId)
        if (!selected.result.value) throw new Error(`Workspace button missing: ${workspace.name}`)
        await delay(1400)
      }
      if (workspace.name === 'product' && triggerResearchRun) {
        if (researchProviderText) {
          const opened = await cdp.send('Runtime.evaluate', {
            expression: `(() => {
              const selector = document.querySelector('.provider-field .ant-select-selector');
              if (!selector) return false;
              selector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
              return true;
            })()`,
            returnByValue: true,
          }, sessionId)
          if (!opened.result.value) throw new Error('Provider selector missing')
          await delay(350)
          const selectedProvider = await cdp.send('Runtime.evaluate', {
            expression: `(() => {
              const expected = ${JSON.stringify(researchProviderText)};
              const option = [...document.querySelectorAll('.ant-select-item-option')]
                .find((item) => item.textContent.includes(expected));
              if (!option) return false;
              option.dispatchEvent(new MouseEvent('click', {bubbles: true}));
              return true;
            })()`,
            returnByValue: true,
          }, sessionId)
          if (!selectedProvider.result.value) throw new Error(`Provider option missing: ${researchProviderText}`)
          await delay(500)
        }
        const started = await cdp.send('Runtime.evaluate', {
          expression: `(() => {
            const button = document.querySelector('.query-action .ant-btn-primary');
            if (!button) return false;
            button.click();
            return true;
          })()`,
          returnByValue: true,
        }, sessionId)
        if (!started.result.value) throw new Error('Research run button missing')
        await delay(progressDelay)
        if (scrollToProgress) {
          await cdp.send('Runtime.evaluate', {
            expression: `document.querySelector('.research-progress, .research-progress-summary')?.scrollIntoView({block: 'start'})`,
          }, sessionId)
          await delay(100)
        }
      }
      const audit = await cdp.send('Runtime.evaluate', {
        expression: `(() => {
        const width = document.documentElement.clientWidth;
        const overflowing = [...document.querySelectorAll('body *')].filter((element) => {
          const rect = element.getBoundingClientRect();
          return rect.width > 0 && (rect.right > width + 1 || rect.left < -1);
        }).slice(0, 20).map((element) => {
          const rect = element.getBoundingClientRect();
          return {
            element: element.tagName.toLowerCase() + (element.className && typeof element.className === 'string' ? '.' + element.className.trim().replace(/\\s+/g, '.') : ''),
            left: Math.round(rect.left), right: Math.round(rect.right), width: Math.round(rect.width),
          };
        });
        return {
          title: document.title,
          viewportWidth: width,
          scrollWidth: document.documentElement.scrollWidth,
          bodyScrollWidth: document.body.scrollWidth,
          overflowing,
        };
      })()`,
        returnByValue: true,
      }, sessionId)
      const screenshot = await cdp.send('Page.captureScreenshot', {
        format: 'png',
        captureBeyondViewport: false,
      }, sessionId)
      await writeFile(
        path.join(outputDir, `${workspace.name}-${viewport.name}.png`),
        Buffer.from(screenshot.data, 'base64'),
      )
      report.push({ viewport, workspace: workspace.name, ...audit.result.value })
    }
  }

  if (email && password) {
    const logoutUrl = new URL('api/auth/logout', targetUrl).href
    await cdp.send('Runtime.evaluate', {
      expression: `fetch(${JSON.stringify(logoutUrl)}, {method: 'POST', credentials: 'include'})`,
      awaitPromise: true,
    }, sessionId)
  }
  await writeFile(path.join(outputDir, 'layout-report.json'), JSON.stringify(report, null, 2))
  process.stdout.write(JSON.stringify(report, null, 2) + '\n')
  await cdp.send('Browser.close')
} finally {
  if (!browser.killed) browser.kill()
  const safePrefix = path.join(os.tmpdir(), 'yanhai-visual-')
  if (profile.startsWith(safePrefix)) await rm(profile, { recursive: true, force: true }).catch(() => {})
}
