import { useEffect, useState } from 'react'
import {
  ApiError,
  LabUnavailable,
  getLabAblation,
  getLabExperiments,
  getLabGoldInventory,
  getLabHealth,
  getLabStoreQuality,
  type StoreQuality,
} from '../api'
import type { ExperimentLedger } from '../types'
import { Empty, Meta, PageHead, ProvenanceNote, SectionHead } from './ui'

/** 研海 Lab（内部）—— 连的是**独立服务**（默认 8767），不是用户端后端。
 *
 *  `src/yanhai/lab_api.py` 是另一个进程：用户端从这一版起根本没有
 *  `/api/experiments` 与 `/api/ablation`，所以即使拿着用户端地址也读不到实验数据。
 *  页面把三种情况分开显示：服务没启动 / 没有内部权限 / 正常。
 */
export function LabPage() {
  const [health, setHealth] = useState<string | null>(null)
  const [ledger, setLedger] = useState<ExperimentLedger | null>(null)
  const [ablation, setAblation] = useState<Record<string, unknown> | null>(null)
  const [quality, setQuality] = useState<StoreQuality | null>(null)
  const [gold, setGold] = useState<{ count: number; entries: Array<{ path: string; bytes: number; sha256_prefix: string }>; note: string } | null>(null)
  const [down, setDown] = useState<string | null>(null)
  const [denied, setDenied] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ablationError, setAblationError] = useState<string | null>(null)

  useEffect(() => {
    const handle = (err: Error, setter: (value: string) => void) => {
      if (err instanceof LabUnavailable) setDown(err.message)
      else if (err instanceof ApiError && (err.status === 403 || err.status === 401)) setter(err.message)
      else setter(err.message)
    }
    getLabHealth()
      .then((payload) => setHealth(payload.version))
      .catch((err: Error) => handle(err, setDown))
    getLabExperiments()
      .then(setLedger)
      .catch((err: Error) => handle(err, (value) => { setDenied(value); setError(value) }))
    getLabAblation()
      .then(setAblation)
      .catch((err: Error) => (err instanceof LabUnavailable ? setDown(err.message) : setAblationError(err.message)))
    getLabStoreQuality()
      .then(setQuality)
      .catch(() => setQuality(null))
    getLabGoldInventory()
      .then(setGold)
      .catch(() => setGold(null))
  }, [])

  if (down) {
    return (
      <>
        <PageHead title="研海 Lab（内部）" summary="内部实验台，独立服务。" />
        <Empty
          title="研海 Lab 服务没有启动"
          body={`${down}。在仓库根目录运行 启动研海Lab.bat，或执行：.venv\\Scripts\\python.exe -m uvicorn yanhai.lab_api:app --host 127.0.0.1 --port 8767`}
          danger
        />
        <div style={{ marginTop: 18 }}>
          <ProvenanceNote
            lines={[
              '用户端（8766）从这一版起不再提供 /api/experiments 与 /api/ablation，实验数据只在这个服务里。',
              '两个服务共用同一份账号库与登录状态：在用户端登录之后，「研海 Lab」页面直接可用。',
              '权限只认数据库里的 is_admin；授权命令：scripts/后台设置内部权限.py --account <邮箱或昵称>。',
            ]}
          />
        </div>
      </>
    )
  }

  if (denied && !ledger) {
    return (
      <>
        <PageHead title="研海 Lab（内部）" summary="内部页面。" />
        <Empty
          title="没有内部权限"
          body={`${denied} 用户端账号看不到实验协议、消融与运行记录。需要的话请让管理员在机房侧执行：scripts/后台设置内部权限.py --account <账号>`}
          danger
        />
        <div style={{ marginTop: 18 }}>
          <ProvenanceNote
            lines={[
              '这一页不在导航里，只能直接用 #/lab 打开；即使知道地址，Lab 服务也会按角色拒绝。',
              '权限只认数据库里的 is_admin，网页上没有任何提权入口。',
              '授权命令：.venv\\Scripts\\python.exe scripts/后台设置内部权限.py --account <邮箱或昵称>',
            ]}
          />
        </div>
      </>
    )
  }

  return (
    <>
      <PageHead
        title="研海 Lab（内部）"
        summary="实验协议、运行记录、消融与数据质量。"
      />

      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel__body">
          <p className="note">
            独立服务已连上（版本 {health ?? '—'}）。运行记录来自 <code>outputs/experiments/</code>，
            消融跑的是仓库内固定的评测案例。
          </p>
        </div>
      </div>

      {error && ledger ? <p className="note" style={{ color: 'var(--danger)' }}>{error}</p> : null}

      {ledger ? (
        <>
          <div className="stats" role="list" style={{ marginBottom: 22 }}>
            <div>
              <dt>协议数</dt>
              <dd className="num">{ledger.protocol_count ?? '—'}</dd>
              
            </div>
            <div>
              <dt>运行次数</dt>
              <dd className="num">{ledger.run_count ?? '—'}</dd>
              
            </div>
            <div>
              <dt>复现命令</dt>
              <dd className="mono" style={{ fontSize: 12 }}>{ledger.run_command || '—'}</dd>
              
            </div>
            <div>
              <dt>实验跟踪</dt>
              <dd style={{ fontSize: 14 }}>{ledger.mlflow_url || '未配置'}</dd>
              
            </div>
          </div>

          <SectionHead title="实验协议" hint={`${ledger.protocols?.length ?? 0} 项`} />
          {!ledger.protocols?.length ? (
            <Empty title="没有协议记录" body="协议写在 tests/experiments/ 里；这里没有读到。" />
          ) : (
            <div className="list list--scroll" style={{ maxHeight: 340 }}>
              {ledger.protocols.map((protocol) => (
                <div className="list__row" key={protocol.slug} style={{ cursor: 'default' }}>
                  <strong>{protocol.title}</strong>
                  <Meta items={[protocol.mode, protocol.evaluation_type, protocol.claim_ceiling]} />
                </div>
              ))}
            </div>
          )}

          <div style={{ marginTop: 24 }}>
            <SectionHead title="运行记录" hint={`${ledger.runs?.length ?? 0} 次`} />
            {!ledger.runs?.length ? (
              <Empty title="没有运行记录" body="还没有跑过实验，或者产物目录不在。跑一次 RUN_PUBLIC_EXPERIMENTS.bat 后这里会有内容。" />
            ) : (
              <div className="list list--scroll" style={{ maxHeight: 340 }}>
                {ledger.runs.map((run) => (
                  <div className="list__row" key={run.run_id} style={{ cursor: 'default' }}>
                    <strong>{run.title || run.experiment}</strong>
                    <Meta
                      items={[
                        run.status,
                        run.generated_at ?? '未记时间',
                        run.evaluation_type,
                        run.git_head ? `HEAD ${run.git_head.slice(0, 7)}` : 'HEAD 未记录',
                        run.git_dirty === null ? '' : run.git_dirty ? '工作树有改动' : '工作树干净',
                      ]}
                    />
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      ) : null}

      {quality ? (
        <div style={{ marginTop: 24 }}>
          <SectionHead
            title="全文知识库的质量账目"
            hint={`引文式证据 ${quality.citation_like} / ${quality.evidence_total}（${(quality.share * 100).toFixed(1)}%）`}
          />
          <div className="panel">
            <div className="panel__body">
              <div className="matrix-wrap">
                <table className="matrix">
                  <thead>
                    <tr>
                      <th scope="col">领域</th>
                      <th scope="col">证据总数</th>
                      <th scope="col">引文式</th>
                      <th scope="col">占比</th>
                    </tr>
                  </thead>
                  <tbody>
                    {quality.domains.map((domain) => (
                      <tr key={domain.domain_id} style={{ cursor: 'default' }}>
                        <th scope="row"><strong>{domain.domain_id}</strong></th>
                        <td className="num">{domain.evidence_total}</td>
                        <td className="num">{domain.citation_like}</td>
                        <td className="num">{(domain.share * 100).toFixed(1)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="note" style={{ marginTop: 10 }}>{quality.note}</p>
              <p className="note">判据：{quality.judged_by}</p>
              {quality.domains[0]?.samples?.length ? (
                <div style={{ marginTop: 10 }}>
                  <p className="note">样例（一眼就能看出是参考文献）：</p>
                  <ul className="checklist">
                    {quality.domains[0].samples.map((sample) => (
                      <li key={sample.evidence_id}>
                        <i>·</i>
                        <span className="mono" style={{ fontSize: 11 }}>{sample.text}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
            <div className="panel__foot">
              这批库是按默认参数建的（`--drop-reference-spans` 关着）。要干净的证据层，需要重建库；
              重建会覆盖现有库并需要重新复核，属于数据侧动作。
            </div>
          </div>
        </div>
      ) : null}

      <div style={{ marginTop: 24 }}>
        <SectionHead title="判定层消融" hint="协议里定下来的变体，不改阈值" />
        {ablationError ? (
          <Empty title="消融跑不起来" body={ablationError} danger />
        ) : ablation ? (
          <div className="panel">
            <div className="panel__body">
              <pre className="json-block" style={{ maxHeight: 420 }}>
                {JSON.stringify(ablation, null, 2).slice(0, 6000)}
              </pre>
            </div>
            <div className="panel__foot">原始结构直出，不美化，也不把某个变体说成"更好"。</div>
          </div>
        ) : (
          <Empty title="正在跑消融" body="消融要跑一遍评测案例，稍等。" />
        )}
      </div>

      {gold ? (
        <div style={{ marginTop: 24 }}>
          <SectionHead title="人工标注材料清单" hint={`${gold.count} 个文件`} />
          <div className="list list--scroll" style={{ maxHeight: 280 }}>
            {gold.entries.map((entry) => (
              <div className="list__row" key={entry.path} style={{ cursor: 'default' }}>
                <strong className="mono" style={{ fontSize: 12 }}>{entry.path}</strong>
                <Meta items={[`${entry.bytes} 字节`, `sha256 ${entry.sha256_prefix}`]} />
              </div>
            ))}
          </div>
          <p className="note" style={{ marginTop: 8 }}>{gold.note}</p>
        </div>
      ) : null}
    </>
  )
}
