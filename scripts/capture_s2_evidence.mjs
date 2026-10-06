// Capture one verified demo run for the provincial S2 evidence-chain figure.
// Credentials are supplied only through environment variables; no source data is changed.
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { chromium } from '@playwright/test'

const baseUrl = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5173'
const apiUrl = process.env.E2E_API_URL ?? 'http://127.0.0.1:8000'
const email = process.env.E2E_EMAIL ?? 'demo@zhixi.local'
const password = process.env.E2E_PASSWORD
const outputDir = process.env.EVIDENCE_OUTPUT_DIR ?? path.resolve('docs/submission/省赛/figures/03-7_真实证据链')
const workspaceId = '44383bdd-43c4-4131-a6c1-69142780b3be'
const conversationId = '5f79dc88-ae26-4180-a8d4-14fa537310dd'
const turnId = '7ea7674c-fa5c-4e9d-bf7a-02e0b392e540'
const runId = '982a0de4-090b-4ab7-a810-e81aa658c576'
const reportId = '19e3f556-f543-4782-a865-b16dd20f0e2a'
const semanticModelId = '3206d469-569a-42d9-831b-131f5394d303'

if (!password) throw new Error('Set E2E_PASSWORD before capturing the real evidence figure.')

const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined,
})
const context = await browser.newContext({ viewport: { width: 1680, height: 1100 }, deviceScaleFactor: 2 })
const page = await context.newPage()
try {
  const login = await context.request.post(`${apiUrl}/api/v1/auth/login`, {
    data: { email, password },
  })
  if (!login.ok()) throw new Error(`API login failed: HTTP ${login.status()}`)
  const { access_token: token } = await login.json()
  const headers = { Authorization: `Bearer ${token}` }
  const viewResponse = await context.request.get(
    `${apiUrl}/api/v1/workspaces/${workspaceId}/analysis-conversations/${conversationId}/view?limit=100`,
    { headers },
  )
  if (!viewResponse.ok()) throw new Error(`Conversation read failed: HTTP ${viewResponse.status()}`)
  const view = await viewResponse.json()
  const record = view.turns.find((item) => item.turn.id === turnId)
  if (!record || record.analysis.run.id !== runId || record.analysis.run.status !== 'completed') {
    throw new Error('The selected conversation turn does not match the expected completed run.')
  }
  const query = record.analysis.artifacts.find((item) => item.artifact_type === 'query_result')
  const chart = record.analysis.artifacts.find((item) => item.artifact_type === 'chart_spec')
  const queryEvidence = record.analysis.evidence.find((item) => item.artifact_id === query?.id)
  const septemberRow = query?.summary.rows.find((row) => String(row[0]).startsWith('2026-09-01'))
  if (!query || !chart || !queryEvidence || chart.summary.source_artifact_id !== query.id
    || !record.analysis.validations.every((item) => item.outcome === 'passed')
    || septemberRow?.[1] !== 3) {
    throw new Error('The query, chart, evidence, validation, or September 3.0 value is inconsistent.')
  }
  const reportResponse = await context.request.get(
    `${apiUrl}/api/v1/workspaces/${workspaceId}/reports?conversation_id=${conversationId}`,
    { headers },
  )
  if (!reportResponse.ok()) throw new Error(`Report read failed: HTTP ${reportResponse.status()}`)
  const reports = await reportResponse.json()
  const report = reports.items.find((item) => item.id === reportId)
  if (report?.status !== 'succeeded' || !report.spec.sections.some((section) => section.source.turn_id === turnId)) {
    throw new Error('The report does not cite the selected run turn.')
  }
  const modelResponse = await context.request.get(
    `${apiUrl}/api/v1/workspaces/${workspaceId}/semantic-models/${semanticModelId}`,
    { headers },
  )
  const model = await modelResponse.json()
  const metric = model.document.metrics.find((item) => item.key === 'defect_rate')
  if (model.status !== 'published' || record.analysis.run.frozen_versions.semantic_model_id !== model.id
    || metric?.formula.numerator !== 'inspection.defect_quantity'
    || metric?.formula.denominator !== 'inspection.inspected_quantity'
    || metric?.formula.scale !== 100 || metric?.unit !== '%') {
    throw new Error('The published metric definition is inconsistent with the selected run.')
  }

  await mkdir(outputDir, { recursive: true })
  await page.goto(`${baseUrl}/login`)
  await page.getByLabel('邮箱').fill(email)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(/\/app\/?$/)

  await page.goto(`${baseUrl}/app/conversations/${conversationId}`)
  await page.locator('.analysis-turn-block').nth(5).getByRole('img', { name: /折线图/ }).waitFor()
  const selectedTurn = page.locator('.analysis-turn-block').nth(5)
  if (!(await selectedTurn.innerText()).includes('3')) throw new Error('Selected turn is not visible in the UI.')
  const [userAvatar, userBubble, agentAvatar, agentBubble] = await Promise.all([
    selectedTurn.locator('.analysis-message.user > span').boundingBox(),
    selectedTurn.locator('.analysis-message.user > div').boundingBox(),
    selectedTurn.locator('.analysis-message.assistant > span').boundingBox(),
    selectedTurn.locator('.analysis-message.assistant > div').boundingBox(),
  ])
  if (!userAvatar || !userBubble || !agentAvatar || !agentBubble
    || userAvatar.x <= userBubble.x || agentAvatar.x >= agentBubble.x) {
    throw new Error('The user/Agent avatars are not on their required right/left sides.')
  }
  await selectedTurn.locator('.analysis-message.user').screenshot({ path: path.join(outputDir, '01a_用户提问_头像在右.png') })
  await selectedTurn.locator('.analysis-message.assistant').screenshot({ path: path.join(outputDir, '01b_Agent回答_头像在左.png') })
  await selectedTurn.locator('.analysis-result-table').screenshot({ path: path.join(outputDir, '01c_可信查询表.png') })
  await selectedTurn.locator('.analysis-chart-card').screenshot({ path: path.join(outputDir, '02_真实折线图.png') })

  await page.goto(`${baseUrl}/app/semantic`)
  await page.getByRole('heading', { name: '语义模型工作台' }).waitFor()
  await page.locator('.model-list-item').filter({ hasText: model.name }).click()
  await page.locator('.metric-card').filter({ hasText: metric.name }).first().screenshot({
    path: path.join(outputDir, '03_已发布指标口径.png'),
  })

  await page.goto(`${baseUrl}/app/analysis/${runId}`)
  await page.locator('.analysis-inspector').getByText('运行详情').waitFor()
  await page.locator('.analysis-technical-details summary').click()
  if (!(await page.locator('.analysis-technical-details').innerText()).includes(runId)) {
    throw new Error('The inspector is showing a different run.')
  }
  await page.locator('.analysis-evidence-list article').filter({ hasText: '查询执行证据' }).screenshot({
    path: path.join(outputDir, '04a_查询执行证据.png'),
  })
  await page.locator('.analysis-validation-list').screenshot({ path: path.join(outputDir, '04b_验证结论.png') })
  await page.locator('.analysis-technical-details').screenshot({ path: path.join(outputDir, '04c_同一运行ID.png') })

  await page.goto(`${baseUrl}/app/conversations/${conversationId}`)
  const reportItem = page.locator('.conversation-report-item').filter({ has: page.getByRole('button', { name: '在线预览' }) }).first()
  await reportItem.getByRole('button', { name: '在线预览' }).click()
  const reportFrame = page.frameLocator('.conversation-report-preview iframe')
  const reportTable = reportFrame.locator('table').first()
  await reportTable.getByText('3.0', { exact: true }).waitFor()
  await reportTable.screenshot({ path: path.join(outputDir, '05_报告中的同一数字.png') })
  await reportFrame.locator('p.evidence').filter({ hasText: turnId }).first().screenshot({
    path: path.join(outputDir, '05b_报告来源引用.png'),
  })

  const manifest = {
    source: 'local demo environment, real persisted run',
    workspaceId, conversationId, turnId, runId, reportId,
    queryArtifactId: query.id,
    chartArtifactId: chart.id,
    queryEvidenceId: queryEvidence.id,
    validatedQueryId: queryEvidence.reference.validated_query_id,
    executionId: queryEvidence.reference.execution_id,
    semanticVersionId: record.analysis.run.frozen_versions.semantic_version_id,
    semanticModelId,
    metric: 'defect_rate = SUM(inspection.defect_quantity) / SUM(inspection.inspected_quantity) × 100%',
    keyNumber: '2026-09-01: 3.0%',
    screenshots: ['01a_用户提问_头像在右.png', '01b_Agent回答_头像在左.png', '01c_可信查询表.png', '02_真实折线图.png', '03_已发布指标口径.png', '04a_查询执行证据.png', '04b_验证结论.png', '04c_同一运行ID.png', '05_报告中的同一数字.png', '05b_报告来源引用.png'],
  }
  await writeFile(path.join(outputDir, '证据来源.json'), `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')
  const images = Object.fromEntries(await Promise.all(manifest.screenshots.map(async (name) => [
    name,
    `data:image/png;base64,${(await readFile(path.join(outputDir, name))).toString('base64')}`,
  ])))
  const image = (name) => `<img src="${images[name]}" alt="${name}">`
  const figureContext = await browser.newContext({ viewport: { width: 2500, height: 1800 }, deviceScaleFactor: 2 })
  const figurePage = await figureContext.newPage()
  await figurePage.setContent(`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>
    *{box-sizing:border-box}body{margin:0;background:#eef3fb;color:#182840;font-family:"Microsoft YaHei",Arial,sans-serif}
    .figure{width:2500px;min-height:1800px;padding:44px 54px 36px}
    h1{margin:0;font-size:45px;letter-spacing:.02em} .subtitle{margin:10px 0 29px;color:#536781;font-size:25px}
    .top{display:grid;grid-template-columns:1fr 1fr;gap:24px}.bottom{display:grid;grid-template-columns:1fr 1.27fr 1.18fr;gap:24px;margin-top:24px}
    .card{min-width:0;padding:20px 22px;background:#fff;border:1px solid #d9e4f1;border-radius:19px;box-shadow:0 6px 20px #213b5d0d}
    .top .card{height:690px}.bottom .card{height:640px}.card h2{display:flex;align-items:center;gap:12px;margin:0 0 16px;font-size:27px}
    .num{display:inline-grid;place-items:center;flex:none;width:42px;height:42px;color:#fff;background:#3155d9;border-radius:12px;font-size:23px}
    .stack{display:grid;gap:10px}.card img{display:block;width:100%;height:auto;max-height:540px;object-fit:contain;border:1px solid #e5eaf2;border-radius:9px}
    .dialogue img{max-height:166px}.dialogue img:last-child{max-height:240px}.metric img{max-height:495px}
    .proof img{max-height:215px}.report img:first-child{max-height:215px}.report img:last-child{max-height:100px}
    .note{margin:14px 0 0;color:#4b5e77;font-size:21px;line-height:1.45}.focus{color:#204bbd;font-weight:800}
    .foot{margin-top:22px;padding:19px 23px;background:#e3edfc;border-radius:14px;color:#294260;font-size:22px;line-height:1.55}
    .foot code{font-family:Consolas,monospace;font-size:19px}
  </style><div class="figure">
    <h1>图 3-7　一条数字的证据链：2026 年 9 月不良率 3.0%</h1>
    <p class="subtitle">同一演示环境、同一已完成运行；界面片段均为真实截图，编号、说明和底部索引为后加标注。</p>
    <div class="top">
      <section class="card dialogue"><h2><span class="num">1</span>用户问题与可信结果</h2><div class="stack">${image('01a_用户提问_头像在右.png')}${image('01b_Agent回答_头像在左.png')}${image('01c_可信查询表.png')}</div><p class="note">9 月的原始查询结果为 <span class="focus">3.0</span>；用户头像在右，Agent 在左。</p></section>
      <section class="card"><h2><span class="num">2</span>同轮生成的趋势图</h2>${image('02_真实折线图.png')}<p class="note">图表引用本轮可信查询产物，不另行填入演示数字。</p></section>
    </div>
    <div class="bottom">
      <section class="card metric"><h2><span class="num">3</span>已发布指标口径</h2>${image('03_已发布指标口径.png')}<p class="note">指标单位为 <span class="focus">%</span>；3.0 即 3.0%。</p></section>
      <section class="card proof"><h2><span class="num">4</span>执行证据与验证</h2><div class="stack">${image('04a_查询执行证据.png')}${image('04b_验证结论.png')}</div><p class="note">查询、执行与语义版本可定位；图表契约和证据完整性均通过。</p></section>
      <section class="card report"><h2><span class="num">5</span>报告中的同一数字</h2><div class="stack">${image('05_报告中的同一数字.png')}${image('05b_报告来源引用.png')}</div><p class="note">报告该片段引用同一轮 Turn，9 月数值仍为 <span class="focus">3.0</span>。</p></section>
    </div>
    <div class="foot">运行 ID：<code>${runId}</code>　·　查询证据：<code>${queryEvidence.id}</code><br>语义版本：<code>${record.analysis.run.frozen_versions.semantic_version_id}</code>　·　报告来源轮次：<code>${turnId}</code></div>
  </div></html>`, { waitUntil: 'load' })
  await figurePage.screenshot({ path: path.join(outputDir, '图3-7_一条数字的真实证据链.png'), fullPage: true })
  await figureContext.close()
  console.log(JSON.stringify({ outputDir, runId, keyNumber: manifest.keyNumber, screenshots: manifest.screenshots }))
} finally {
  await browser.close()
}
