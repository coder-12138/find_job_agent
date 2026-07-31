import { useEffect, useMemo, useState } from "react";
import * as api from "./api";
import "./styles.css";

type Section = "profiles" | "applications" | "learning";
type DraftField = { key: string; value: string; confidence: number };

const FIELD_LABELS: Record<string, string> = {
  full_name: "姓名",
  email: "邮箱",
  phone: "手机",
  gender: "性别",
  address: "所在地",
  education: "教育经历",
  work_experience: "工作经历",
  project_experience: "项目经历",
  skills: "技能",
  awards: "荣誉奖项",
  self_introduction: "个人总结",
};

const STATE_LABELS: Record<string, string> = {
  draft: "待准备",
  ready_for_review: "待核对",
  awaiting_login: "等待登录/接管",
  awaiting_user_submit: "等待你最终提交",
  submitted: "已投递（有回执）",
  outcome_unknown: "结果未知",
  failed: "失败",
  cancelled: "已取消",
};

function App() {
  const [section, setSection] = useState<Section>("profiles");
  const [health, setHealth] = useState<api.CoreHealth | null>(null);
  const [profiles, setProfiles] = useState<api.Profile[]>([]);
  const [applications, setApplications] = useState<api.Application[]>([]);
  const [hints, setHints] = useState<api.InteractionHint[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refresh = async () => {
    const [status, nextProfiles, nextApplications, nextHints] = await Promise.all([
      api.loadCoreStatus(),
      api.listProfiles(),
      api.listApplications(),
      api.listHints(),
    ]);
    setHealth(status.health);
    setProfiles(nextProfiles);
    setApplications(nextApplications);
    setHints(nextHints);
  };

  useEffect(() => {
    refresh().catch((reason: unknown) => setError(readError(reason)));
  }, []);

  const run = async (action: () => Promise<unknown>, success: string) => {
    setError("");
    setMessage("");
    try {
      await action();
      await refresh();
      setMessage(success);
    } catch (reason) {
      setError(readError(reason));
      throw reason;
    }
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">J</span>
          <div><strong>求职投递助手</strong><small>可靠优先 · 人工最终提交</small></div>
        </div>
        <nav aria-label="任务导航">
          <NavItem active={section === "profiles"} index="01" title="候选人档案" detail="PDF 提取、字段确认与版本管理" onClick={() => setSection("profiles")} />
          <NavItem active={section === "applications"} index="02" title="职位申请" detail="固定档案版本、核对并受管投递" onClick={() => setSection("applications")} />
          <NavItem active={section === "learning"} index="03" title="接管经验" detail="审核人工操作沉淀的定位提示" onClick={() => setSection("learning")} />
        </nav>
        <div className="sidebar-note">
          <span className={health ? "online-dot" : "offline-dot"}>{health ? "核心在线" : "正在连接"}</span>
          <p>登录必须在弹出的受管浏览器完成。系统填表后会停住，最终提交按钮始终由你点击。</p>
        </div>
      </aside>

      <main>
        <header className="topbar">
          <div><p className="eyebrow">RELIABILITY-FIRST WORKSPACE</p><h1>{sectionTitle(section)}</h1></div>
          <div className="top-actions"><span>Schema v{health?.schema_version ?? "…"}</span><a href="/docs" target="_blank" rel="noreferrer">API 文档</a></div>
        </header>
        {(message || error) && <div className={`notice ${error ? "error" : "success"}`}>{error || message}</div>}
        {section === "profiles" && <ProfilesPanel profiles={profiles} run={run} />}
        {section === "applications" && <ApplicationsPanel profiles={profiles} applications={applications} run={run} />}
        {section === "learning" && <LearningPanel hints={hints} run={run} />}
      </main>
    </div>
  );
}

function NavItem(props: { active: boolean; index: string; title: string; detail: string; onClick: () => void }) {
  return <button className={`nav-item ${props.active ? "active" : ""}`} type="button" onClick={props.onClick}>
    <span>{props.index}</span><span><strong>{props.title}</strong><small>{props.detail}</small></span>
  </button>;
}

function ProfilesPanel({ profiles, run }: { profiles: api.Profile[]; run: Runner }) {
  const [uploading, setUploading] = useState(false);
  const [resourceId, setResourceId] = useState("");
  const [fileName, setFileName] = useState("");
  const [quality, setQuality] = useState<api.ResumeExtraction["quality"] | null>(null);
  const [draft, setDraft] = useState<DraftField[]>([]);
  const [targetProfileId, setTargetProfileId] = useState("new");
  const [proposal, setProposal] = useState<api.ChangeProposal | null>(null);
  const [selectedChanges, setSelectedChanges] = useState<string[]>([]);
  const [expandedProfile, setExpandedProfile] = useState<string | null>(null);
  const [versions, setVersions] = useState<Record<string, api.ProfileVersion[]>>({});

  const onFile = async (file?: File) => {
    if (!file) return;
    setUploading(true); setProposal(null);
    try {
      const result = await api.uploadAndExtract(file);
      setResourceId(result.resource.resource_id);
      setFileName(result.resource.original_name);
      setQuality(result.extraction.quality);
      setDraft(result.extraction.proposed_fields.map((field) => ({
        key: field.field_key,
        value: typeof field.value === "string" ? field.value : JSON.stringify(field.value, null, 2),
        confidence: field.confidence,
      })));
    } finally { setUploading(false); }
  };

  const fields = () => Object.fromEntries(draft.filter((item) => item.key.trim()).map((item) => [item.key.trim(), item.value]));
  const save = async () => {
    if (targetProfileId === "new") {
      await run(() => api.createProfile(fields(), resourceId), "候选人档案 v1 已建立，原 PDF 和字段均已加密保存。");
      resetUpload();
      return;
    }
    const profile = profiles.find((item) => item.id === targetProfileId);
    if (!profile) return;
    const created = await api.createProposal(profile, resourceId, fields());
    setProposal(created);
    setSelectedChanges(Object.keys(created.changes));
  };
  const resetUpload = () => { setResourceId(""); setFileName(""); setQuality(null); setDraft([]); setProposal(null); };
  const loadVersions = async (profileId: string) => {
    if (expandedProfile === profileId) { setExpandedProfile(null); return; }
    const loaded = await api.listVersions(profileId);
    setVersions((old) => ({ ...old, [profileId]: loaded }));
    setExpandedProfile(profileId);
  };

  return <div className="workspace-grid">
    <section className="card upload-card">
      <div className="card-heading"><div><p className="step">第一步</p><h2>上传或更新 PDF 简历</h2></div><span className="privacy-badge">本地加密</span></div>
      {!resourceId ? <label className="drop-zone">
        <input type="file" accept="application/pdf" onChange={(event) => onFile(event.target.files?.[0])} disabled={uploading} />
        <strong>{uploading ? "正在提取文本和版面…" : "选择 PDF 简历"}</strong>
        <span>优先读取文本层，质量不足时仅在本机 OCR；最大 20 MiB</span>
      </label> : <>
        <div className="file-summary"><div><strong>{fileName}</strong><span>{quality?.page_count} 页 · {quality?.character_count} 字符 · {quality?.ocr_pages.length ? `OCR ${quality.ocr_pages.join(", ")} 页` : "文本层"}</span></div><button className="text-button" onClick={resetUpload}>重新选择</button></div>
        {quality?.needs_review && <div className="review-warning">提取结果需要人工核对。低置信度字段不会被当成既定事实。</div>}
        <label className="field-label">保存方式<select value={targetProfileId} onChange={(event) => setTargetProfileId(event.target.value)}><option value="new">建立新的候选人档案</option>{profiles.map((profile) => <option key={profile.id} value={profile.id}>更新现有档案 · 当前 v{profile.active_version.version_number}</option>)}</select></label>
        <div className="field-editor">{draft.map((item, index) => <div className="field-row" key={`${item.key}-${index}`}>
          <div className="field-meta"><input value={item.key} aria-label="字段名" onChange={(event) => setDraft((old) => old.map((entry, i) => i === index ? { ...entry, key: event.target.value } : entry))} /><span className={item.confidence < .8 ? "confidence low" : "confidence"}>{Math.round(item.confidence * 100)}%</span></div>
          <textarea value={item.value} aria-label={`${item.key} 字段值`} onChange={(event) => setDraft((old) => old.map((entry, i) => i === index ? { ...entry, value: event.target.value } : entry))} />
        </div>)}</div>
        <button className="primary" disabled={!draft.length || !!proposal} onClick={() => save().catch(() => undefined)}>{targetProfileId === "new" ? "确认并建立档案" : "生成字段差异提案"}</button>
      </>}
      {proposal && <div className="proposal-panel"><h3>自主选择增量更新内容</h3><p>未勾选字段沿用旧版本；接受后创建独立新版本，不覆盖旧版本。</p>{Object.entries(proposal.changes).map(([key, change]) => <label className="change-item" key={key}><input type="checkbox" checked={selectedChanges.includes(key)} onChange={(event) => setSelectedChanges((old) => event.target.checked ? [...old, key] : old.filter((item) => item !== key))} /><span><strong>{FIELD_LABELS[key] ?? key}</strong><small>旧：{display(change.old)}</small><small>新：{display(change.new)}</small></span></label>)}
        <button className="primary" onClick={() => { const profile = profiles.find((item) => item.id === targetProfileId); if (!profile) return; run(() => api.acceptProposal(proposal.id, selectedChanges, profile.row_version), "已按选择创建独立档案版本并切换为当前版本。").then(resetUpload).catch(() => undefined); }}>接受所选字段并新建版本</button>
      </div>}
    </section>

    <section className="card profile-list"><div className="card-heading"><div><p className="step">档案库</p><h2>版本管理</h2></div><span className="count-badge">{profiles.length}</span></div>
      {!profiles.length && <Empty text="尚未建立候选人档案。先上传一份 PDF。" />}
      {profiles.map((profile) => <article className="profile-item" key={profile.id}><button className="profile-summary" onClick={() => loadVersions(profile.id)}><Avatar name={String(profile.active_version.fields.full_name ?? "候选人")} /><span><strong>{String(profile.active_version.fields.full_name ?? "未命名候选人")}</strong><small>当前 v{profile.active_version.version_number} · {Object.keys(profile.active_version.fields).length} 个字段</small></span><b>{expandedProfile === profile.id ? "收起" : "管理"}</b></button>
        {expandedProfile === profile.id && <div className="version-list">{(versions[profile.id] ?? []).map((version) => <div className={`version-item ${version.id === profile.active_version_id ? "current" : ""}`} key={version.id}><div><strong>v{version.version_number}</strong><span>{version.status === "archived" ? "已归档" : version.id === profile.active_version_id ? "当前使用" : "可切换"}</span><small>{new Date(version.created_at).toLocaleString()}</small></div><div className="inline-actions">{version.status !== "archived" && version.id !== profile.active_version_id && <button onClick={() => run(() => api.activateVersion(profile.id, version.id, profile.row_version), `已切换到 v${version.version_number}`).then(() => loadVersions(profile.id)).catch(() => undefined)}>切换</button>}{version.id !== profile.active_version_id && version.status !== "archived" && <button onClick={() => run(() => api.archiveVersion(profile.id, version.id, profile.row_version), `v${version.version_number} 已归档`).then(() => loadVersions(profile.id)).catch(() => undefined)}>归档</button>}{version.id !== profile.active_version_id && <button className="danger" onClick={() => { if (window.confirm(`确认删除 v${version.version_number}？已被申请引用的版本不会被删除。`)) run(() => api.deleteVersion(profile.id, version.id, profile.row_version), `v${version.version_number} 已删除`).then(() => loadVersions(profile.id)).catch(() => undefined); }}>删除</button>}</div></div>)}</div>}
      </article>)}
    </section>
  </div>;
}

function ApplicationsPanel({ profiles, applications, run }: { profiles: api.Profile[]; applications: api.Application[]; run: Runner }) {
  const [url, setUrl] = useState(""); const [title, setTitle] = useState(""); const [company, setCompany] = useState("");
  const [versionId, setVersionId] = useState(profiles[0]?.active_version_id ?? ""); const [browserMessage, setBrowserMessage] = useState<Record<string, string>>({});
  useEffect(() => { if (!versionId && profiles[0]) setVersionId(profiles[0].active_version_id); }, [profiles, versionId]);
  const versionsById = useMemo(() => new Map(profiles.map((profile) => [profile.active_version.id, profile.active_version])), [profiles]);
  const command = async (application: api.Application, kind: "prepare" | "approve" | "open" | "continue" | "observe") => {
    if (kind === "prepare") {
      const profile = versionsById.get(application.profile_version_id);
      if (!profile) throw new Error("当前界面找不到申请固定的档案版本，请刷新后重试");
      await run(() => api.prepareApplication(application.id, profile.fields, application.row_version), "待填字段快照已生成，请核对后确认。"); return;
    }
    if (kind === "approve") { await run(() => api.approveApplication(application.id, application.row_version), "材料已确认，可以打开受管浏览器登录。"); return; }
    const action = kind === "open" ? api.openBrowser : kind === "continue" ? api.continueBrowser : api.observeSubmission;
    const result = await action(application.id);
    setBrowserMessage((old) => ({ ...old, [application.id]: result.message }));
    await run(async () => undefined, result.message);
  };
  return <div className="application-layout"><section className="card new-application"><div className="card-heading"><div><p className="step">新建任务</p><h2>固定职位与档案版本</h2></div><span className="platform-badge">飞书招聘</span></div>
    {!profiles.length ? <Empty text="请先建立候选人档案。" /> : <div className="form-stack"><label>飞书职位链接<input value={url} placeholder="https://jobs.feishu.cn/..." onChange={(event) => setUrl(event.target.value)} /></label><div className="two-cols"><label>职位名称（可选）<input value={title} onChange={(event) => setTitle(event.target.value)} /></label><label>公司（可选）<input value={company} onChange={(event) => setCompany(event.target.value)} /></label></div><label>档案版本<select value={versionId} onChange={(event) => setVersionId(event.target.value)}>{profiles.map((profile) => <option key={profile.id} value={profile.active_version_id}>{String(profile.active_version.fields.full_name ?? "候选人")} · v{profile.active_version.version_number}</option>)}</select></label><button className="primary" disabled={!url || !versionId} onClick={() => run(() => api.createApplication({ source_url: url, profile_version_id: versionId, title: title || undefined, company: company || undefined }), "职位申请任务已建立。").then(() => { setUrl(""); setTitle(""); setCompany(""); }).catch(() => undefined)}>建立申请任务</button></div>}
  </section>
  <section className="application-list"><div className="section-heading"><div><p className="step">任务队列</p><h2>投递进度</h2></div><span>{applications.length} 个任务</span></div>{!applications.length && <div className="card"><Empty text="尚无职位申请任务。" /></div>}{applications.map((application) => <article className="card application-item" key={application.id}><div className="application-header"><div><span className={`state state-${application.state}`}>{STATE_LABELS[application.state] ?? application.state}</span><h3>{application.title || "未命名职位"}</h3><p>{application.company || "飞书招聘"} · <a href={application.source_url} target="_blank" rel="noreferrer">查看原链接</a></p></div><span className="version-chip">档案固定 {profileVersionName(profiles, application.profile_version_id)}</span></div><div className="state-reason">{browserMessage[application.id] || application.state_reason || "任务已建立，等待下一步。"}</div>{application.form_values && <details><summary>查看已核对字段快照</summary><pre>{JSON.stringify(application.form_values, null, 2)}</pre></details>}<div className="task-actions">{application.state === "draft" && <button className="primary" onClick={() => command(application, "prepare").catch((reason) => setBrowserMessage((old) => ({ ...old, [application.id]: readError(reason) })))}>生成待核对材料</button>}{application.state === "ready_for_review" && <button className="primary" onClick={() => command(application, "approve").catch(() => undefined)}>确认材料无误</button>}{application.state === "awaiting_login" && <><button className="primary" onClick={() => command(application, "open").catch((reason) => setBrowserMessage((old) => ({ ...old, [application.id]: readError(reason) })))}>打开受管浏览器</button><button onClick={() => command(application, "continue").catch((reason) => setBrowserMessage((old) => ({ ...old, [application.id]: readError(reason) })))}>我已登录 / 继续检查</button></>}{application.state === "awaiting_user_submit" && <button className="primary attention" onClick={() => command(application, "observe").catch((reason) => setBrowserMessage((old) => ({ ...old, [application.id]: readError(reason) })))}>我已在窗口提交，检查回执</button>}</div>{application.state === "awaiting_login" && <p className="takeover-note">请只在弹出的专用窗口登录。复制链接到普通浏览器登录不会把登录状态带回本任务。</p>}{application.state === "awaiting_user_submit" && <p className="takeover-note strong">系统不会点击最终提交。请在受管窗口逐项检查后亲自提交，再回这里检查回执。</p>}</article>)}</section></div>;
}

function LearningPanel({ hints, run }: { hints: api.InteractionHint[]; run: Runner }) {
  return <div className="learning-layout"><section className="card learning-intro"><p className="step">受控学习</p><h2>把人工接管沉淀为可审核规则</h2><p>系统只记录“这个页面上的某个字段可通过哪种定位方式找到”，不保存你输入的值，也不会训练黑盒模型。新观察默认是候选提示，只有你批准后，下次同类页面才会优先尝试。</p><div className="learning-flow"><span>人工操作</span><b>→</b><span>候选提示</span><b>→</b><span>你审核</span><b>→</b><span>确定性复用</span></div></section><section className="card"><div className="card-heading"><div><p className="step">提示库</p><h2>待审核与已处理</h2></div><span className="count-badge">{hints.length}</span></div>{!hints.length && <Empty text="尚未观察到可复用的人工字段操作。" />}{hints.map((hint) => <div className="hint-item" key={hint.id}><div><strong>{FIELD_LABELS[hint.field_key] ?? hint.field_key}</strong><span>{hint.locator_strategy}: {hint.locator_value}</span><small>观察成功 {hint.success_count} 次 · {hint.review_status}</small></div>{hint.review_status === "candidate" && <div className="inline-actions"><button onClick={() => run(() => api.reviewHint(hint.id, "approved"), "定位提示已批准，下次同页表单可以复用。").catch(() => undefined)}>批准</button><button className="danger" onClick={() => run(() => api.reviewHint(hint.id, "disabled"), "定位提示已禁用。").catch(() => undefined)}>禁用</button></div>}</div>)}</section></div>;
}

function Avatar({ name }: { name: string }) { return <span className="avatar">{name.slice(0, 1).toUpperCase()}</span>; }
function Empty({ text }: { text: string }) { return <div className="empty"><span>○</span><p>{text}</p></div>; }
function display(value: unknown) { if (value === null || value === undefined || value === "") return "（空）"; return typeof value === "string" ? value : JSON.stringify(value); }
function readError(reason: unknown) { return reason instanceof Error ? reason.message : "发生未知错误"; }
function sectionTitle(section: Section) { return section === "profiles" ? "候选人档案" : section === "applications" ? "职位申请任务" : "人工接管经验"; }
function profileVersionName(profiles: api.Profile[], versionId: string) { const profile = profiles.find((item) => item.active_version.id === versionId); return profile ? `v${profile.active_version.version_number}` : versionId.slice(0, 8); }
type Runner = (action: () => Promise<unknown>, success: string) => Promise<void>;

export default App;
