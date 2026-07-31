/* ============================================================
   简历自动投递 Agent — Web UI 前端逻辑
   纯原生 JS，无外部依赖
   ============================================================ */

(function () {
"use strict";

/* ---------------- 常量 ---------------- */
const PHASES = [
    { key: "search", label: "搜索" },
    { key: "recommend", label: "推荐" },
    { key: "polish", label: "润色" },
    { key: "fill", label: "填表" },
    { key: "confirm", label: "确认" },
    { key: "submit", label: "投递" },
];
const PHASE_INDEX = Object.fromEntries(PHASES.map((p, i) => [p.key, i]));

const RECRUITMENT_TYPES = ["校招", "社招", "日常实习", "暑期实习（转正实习）"];
const API_SETTINGS_STORAGE_KEY = "find-job-agent.api-settings.v1";

/* 简历字段中文标签（resume_review） */
const RESUME_LABELS = {
    self_introduction: "自我介绍",
    project_highlights: "项目亮点",
    skill_highlights: "技能亮点",
    work_highlights: "工作亮点",
    summary: "总结",
};
const RESUME_ARRAY_FIELDS = {
    project_highlights: [
        ["name", "项目名称"],
        ["role", "担任角色"],
        ["description", "项目描述"],
        ["relevance_to_jd", "与岗位的相关性"],
    ],
    skill_highlights: [
        ["skill", "技能名称"],
        ["level", "掌握程度"],
        ["relevance", "与岗位的相关性"],
    ],
    work_highlights: [
        ["company", "公司名称"],
        ["position", "职位名称"],
        ["description", "工作描述"],
        ["relevance", "与岗位的相关性"],
    ],
};

/* ---------------- 应用状态 ---------------- */
const state = {
    currentView: "home",
    recruitmentTypes: RECRUITMENT_TYPES,
    agentApi: {
        verified: false,
        autoVerifyAttempted: false,
    },
    profiles: {
        items: [],
        selectedVersionId: null,
    },
    companies: [], // [{uid, company_name, recruitment_type, referral_code, job_keywords, preferred_cities, parallel}]
    session: {
        id: null,
        ws: null,
        wsReconnectTimer: null,
        companies: {}, // {companyName: {status, phase, message, form_filled, submitted, error}}
        phase: null, // 全局当前阶段
        completedPhases: new Set(),
        results: null,
        status: null,
    },
    chat: {
        messages: [], // {role: "user"|"agent", content: string, time: string}
    },
};

let companyUidCounter = 0;

/* ---------------- 工具函数 ---------------- */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function el(tag, attrs = {}, children = []) {
    const node = document.createElement(tag);
    Object.entries(attrs).forEach(([k, v]) => {
        if (k === "class") node.className = v;
        else if (k === "html") node.innerHTML = v;
        else if (k === "text") node.textContent = v;
        else if (k.startsWith("on") && typeof v === "function") {
            node.addEventListener(k.slice(2).toLowerCase(), v);
        } else if (v !== null && v !== undefined) {
            node.setAttribute(k, v);
        }
    });
    (Array.isArray(children) ? children : [children]).forEach((c) => {
        if (c == null) return;
        if (typeof c === "string" || typeof c === "number") {
            node.appendChild(document.createTextNode(String(c)));
        } else {
            node.appendChild(c);
        }
    });
    return node;
}

function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function formatTime(iso) {
    if (!iso) return "—";
    try {
        const d = new Date(iso);
        if (isNaN(d.getTime())) return iso;
        return d.toLocaleString("zh-CN", { hour12: false });
    } catch { return iso; }
}

function formatSize(bytes) {
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    let n = bytes;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function nowTimeStr() {
    return new Date().toLocaleTimeString("zh-CN", { hour12: false });
}

/* ---------------- Toast ---------------- */
function toast(message, type = "info", title = "") {
    const container = $("#toastContainer");
    const icons = {
        success: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
        error: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
        warning: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
        info: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    };
    const t = el("div", { class: `toast toast-${type}` }, [
        el("div", { class: "toast-icon", html: icons[type] || icons.info }),
        el("div", { class: "toast-body" }, [
            title ? el("div", { class: "toast-title", text: title }) : null,
            el("div", { class: "toast-msg", text: message }),
        ]),
    ]);
    container.appendChild(t);
    setTimeout(() => {
        t.classList.add("out");
        setTimeout(() => t.remove(), 200);
    }, 3800);
}

/* ---------------- API 助手 ---------------- */
async function api(path, options = {}) {
    const opts = { ...options, headers: { ...(options.headers || {}) } };
    if (opts.json !== undefined) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(opts.json);
        delete opts.json;
    }
    const res = await fetch(path, opts);
    let data;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
        data = await res.json();
    } else {
        data = await res.text();
    }
    if (!res.ok) {
        const msg = (data && data.detail) || (typeof data === "string" ? data : `请求失败 (${res.status})`);
        throw new Error(msg);
    }
    return data;
}

/* ---------------- 导航 ---------------- */
const VIEW_TITLES = {
    home: "投递任务",
    files: "文件管理",
    "agent-api": "Agent 连接",
    settings: "系统设置",
    monitor: "运行监控",
    memory: "记忆管理",
};

function switchView(view) {
    state.currentView = view;
    $$(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.view === view));
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
    $("#pageTitle").textContent = VIEW_TITLES[view] || "";
    // 关闭移动端侧边栏
    $("#sidebar").classList.remove("open");
    // 视图打开时按需加载数据
    if (view === "files") {
        loadUploads();
        loadProfiles();
    }
    if (view === "agent-api") loadAgentApiSettings();
    if (view === "settings") loadSettings();
    if (view === "memory") loadMemory();
}

/* ---------------- 投递任务视图 ---------------- */
function createCompanyRow(data = {}) {
    const uid = `c${++companyUidCounter}`;
    const company = {
        uid,
        company_name: data.company_name || "",
        recruitment_type: data.recruitment_type || RECRUITMENT_TYPES[0],
        referral_code: data.referral_code || "",
        job_keywords: data.job_keywords || "",
        preferred_cities: data.preferred_cities || [],
        application_url: data.application_url || "",
    };
    state.companies.push(company);

    const row = el("div", { class: "company-row", "data-uid": uid });

    const head = el("div", { class: "company-row-head" }, [
        el("div", { class: "company-row-index" }, [
            el("span", { class: "num", text: state.companies.length }),
            el("span", { text: "公司" }),
        ]),
        el("button", {
            class: "btn btn-ghost btn-sm btn-remove",
            title: "移除",
            onclick: () => removeCompanyRow(uid),
        }, [
            el("span", {
                html: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/></svg>',
            }),
        ]),
    ]);

    const typeOptions = RECRUITMENT_TYPES.map(
        (t) => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`
    ).join("");

    const fields = el("div", { class: "company-fields" }, [
        // 公司名
        el("div", {}, [
            el("label", { class: "field-mini-label", text: "公司名称 *" }),
            el("input", {
                class: "input",
                type: "text",
                placeholder: "如：字节跳动",
                value: company.company_name,
                oninput: (e) => { company.company_name = e.target.value; },
            }),
        ]),
        // 招聘类型
        el("div", {}, [
            el("label", { class: "field-mini-label", text: "招聘类型" }),
            el("select", {
                class: "select",
                html: typeOptions,
                onchange: (e) => { company.recruitment_type = e.target.value; },
            }),
        ]),
        // 内推码
        el("div", {}, [
            el("label", { class: "field-mini-label", text: "内推码（可选）" }),
            el("input", {
                class: "input",
                type: "text",
                placeholder: "如：XYZ123",
                value: company.referral_code,
                oninput: (e) => { company.referral_code = e.target.value; },
            }),
        ]),
        // 岗位关键词
        el("div", {}, [
            el("label", { class: "field-mini-label", text: "岗位关键词（可选）" }),
            el("input", {
                class: "input",
                type: "text",
                placeholder: "如：后端开发 Java",
                value: company.job_keywords,
                oninput: (e) => { company.job_keywords = e.target.value; },
            }),
        ]),
        // 意向城市
        el("div", { class: "full" }, [
            el("label", { class: "field-mini-label", text: "意向城市（逗号分隔，可选）" }),
            el("input", {
                class: "input",
                type: "text",
                placeholder: "如：北京,上海,深圳",
                value: company.preferred_cities.join(","),
                oninput: (e) => {
                    company.preferred_cities = e.target.value
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean);
                },
            }),
        ]),
        // 手动招聘链接
        el("div", { class: "full" }, [
            el("label", { class: "field-mini-label", text: "招聘官网 / 职位列表链接（可选，推荐）" }),
            el("input", {
                class: "input",
                type: "url",
                placeholder: "https://...  填写后将跳过搜索引擎，直接访问该页面",
                value: company.application_url,
                oninput: (e) => { company.application_url = e.target.value.trim(); },
            }),
        ]),
    ]);

    // 设置招聘类型选中
    fields.querySelector("select").value = company.recruitment_type;

    row.appendChild(head);
    row.appendChild(fields);
    return row;
}

function reindexCompanies() {
    $$("#companyList .company-row").forEach((row, i) => {
        const num = row.querySelector(".company-row-index .num");
        if (num) num.textContent = i + 1;
    });
}

function removeCompanyRow(uid) {
    state.companies = state.companies.filter((c) => c.uid !== uid);
    const row = $(`#companyList .company-row[data-uid="${uid}"]`);
    if (row) row.remove();
    reindexCompanies();
    if (state.companies.length === 0) {
        $("#companyList").appendChild(createCompanyRow());
    }
}

async function loadRecruitmentTypes() {
    try {
        const data = await api("/api/recruitment-types");
        if (data.recruitment_types && data.recruitment_types.length) {
            state.recruitmentTypes = data.recruitment_types;
        }
    } catch (e) {
        // 使用默认值即可
        console.warn("加载招聘类型失败", e);
    }
}

async function loadUserInfoSummary() {
    const container = $("#userInfoSummary");
    try {
        const mem = await api("/api/memory");
        const src = mem.source_user_info || {};
        // 提取关键字段
        const keys = [
            "name", "phone", "email", "gender", "current_city",
            "school", "major", "degree", "wechat",
        ];
        const items = keys
            .filter((k) => src[k])
            .map((k) => ({
                k: FIELD_LABELS[k] || k,
                v: src[k],
            }));
        if (!items.length) {
            container.innerHTML = '<div class="info-skel">未找到用户信息，请确认已配置个人信息文件</div>';
            return;
        }
        container.innerHTML = "";
        items.forEach(({ k, v }) => {
            container.appendChild(
                el("div", { class: "info-item" }, [
                    el("div", { class: "k", text: k }),
                    el("div", { class: "v", text: v }),
                ])
            );
        });
    } catch (e) {
        container.innerHTML = `<div class="info-skel">加载失败：${escapeHtml(e.message)}</div>`;
    }
}

const FIELD_LABELS = {
    name: "姓名",
    english_name: "英文名",
    gender: "性别",
    birthday: "生日",
    phone: "电话",
    email: "邮箱",
    id_type: "证件类型",
    id_number: "证件号",
    nationality: "国籍",
    ethnicity: "民族",
    political_status: "政治面貌",
    marital_status: "婚姻状况",
    wechat: "微信",
    qq: "QQ",
    province: "省份",
    city: "城市",
    address: "地址",
    zip_code: "邮编",
    website: "网站",
    current_city: "当前城市",
    school: "学校",
    major: "专业",
    degree: "学历",
    gpa: "GPA",
    self_introduction: "自我介绍",
};

async function startSession() {
    // 校验
    const companies = state.companies
        .map((c) => ({
            company_name: c.company_name.trim(),
            recruitment_type: c.recruitment_type,
            referral_code: c.referral_code.trim(),
            job_keywords: c.job_keywords.trim(),
            preferred_cities: c.preferred_cities,
            application_url: c.application_url.trim(),
        }))
        .filter((c) => c.company_name);

    if (!companies.length) {
        toast("请至少添加一家公司（公司名称必填）", "warning", "无法开始");
        return;
    }
    const invalidUrlCompany = companies.find(
        (c) => c.application_url && !/^https?:\/\//i.test(c.application_url)
    );
    if (invalidUrlCompany) {
        toast(
            `${invalidUrlCompany.company_name} 的招聘链接必须以 http:// 或 https:// 开头`,
            "warning",
            "链接格式错误"
        );
        return;
    }
    if (!(await ensureAgentApiVerified())) return;
    if (!state.profiles.selectedVersionId) {
        await loadProfiles();
    }
    if (!state.profiles.selectedVersionId) {
        toast("请先在文件管理中上传 PDF，并确认一个候选人档案版本", "warning", "缺少候选人档案");
        switchView("files");
        return;
    }

    const parallel = $("#parallelMode").checked;

    const btn = $("#startBtn");
    btn.disabled = true;
    btn.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="spin"><circle cx="12" cy="12" r="10" stroke-dasharray="40 20"/></svg> 启动中…';

    try {
        const res = await api("/api/sessions", {
            method: "POST",
            json: {
                companies,
                parallel,
                profile_version_id: state.profiles.selectedVersionId,
            },
        });
        state.session.id = res.session_id;
        state.session.companies = {};
        state.session.phase = null;
        state.session.completedPhases = new Set();
        state.session.results = null;
        state.session.status = res.status;
        // 初始化公司状态
        companies.forEach((c) => {
            state.session.companies[c.company_name] = {
                status: "pending",
                phase: null,
                message: "",
                form_filled: false,
                submitted: false,
                error: "",
            };
        });
        toast(`会话已创建：${res.session_id}`, "success", "开始投递");
        switchView("monitor");
        initMonitor();
        connectWebSocket(res.session_id);
    } catch (e) {
        toast(e.message, "error", "创建会话失败");
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg> 开始投递';
    }
}

/* ---------------- 文档投递视图 ---------------- */
async function startDocumentSession() {
    // 收集表单数据
    const docUrl = $("#docUrl").value.trim();
    const jobKeyword = $("#docJobKeyword").value.trim();
    const industry = $("#docIndustry").value.trim();
    const city = $("#docCity").value.trim();
    const recruitmentType = $("#docRecruitmentType").value;
    const parallel = $("#docParallelMode").checked;

    // 表单验证：doc_url 必填且含 docs.qq.com
    if (!docUrl) {
        toast("请填写腾讯文档链接", "warning", "无法开始");
        return;
    }
    if (docUrl.indexOf("docs.qq.com") === -1) {
        toast("请提供有效的腾讯文档链接（需包含 docs.qq.com）", "warning", "链接无效");
        return;
    }
    if (!(await ensureAgentApiVerified())) return;

    const btn = $("#startDocBtn");
    btn.disabled = true;
    btn.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="spin"><circle cx="12" cy="12" r="10" stroke-dasharray="40 20"/></svg> 启动中…';

    try {
        const res = await api("/api/sessions/document", {
            method: "POST",
            json: {
                doc_url: docUrl,
                job_keyword: jobKeyword,
                industry,
                city,
                recruitment_type: recruitmentType,
                parallel,
            },
        });
        state.session.id = res.session_id;
        state.session.companies = {};
        state.session.phase = null;
        state.session.completedPhases = new Set();
        state.session.results = null;
        state.session.status = res.status;
        toast(`会话已创建：${res.session_id}`, "success", "开始投递");
        // 跳转到运行监控视图并连接 WebSocket（复用现有逻辑）
        switchView("monitor");
        initMonitor();
        connectWebSocket(res.session_id);
    } catch (e) {
        toast(e.message, "error", "创建会话失败");
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg> 开始投递';
    }
}

/* ---------------- 文件管理 ---------------- */
function setupDropzone() {
    const dz = $("#dropzone");
    const input = $("#fileInput");

    dz.addEventListener("click", () => input.click());
    dz.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            input.click();
        }
    });

    ["dragenter", "dragover"].forEach((evt) => {
        dz.addEventListener(evt, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dz.classList.add("dragover");
        });
    });
    ["dragleave", "drop"].forEach((evt) => {
        dz.addEventListener(evt, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dz.classList.remove("dragover");
        });
    });
    dz.addEventListener("drop", (e) => {
        const files = e.dataTransfer.files;
        if (files && files.length) uploadFiles(files);
    });
    input.addEventListener("change", (e) => {
        if (e.target.files.length) uploadFiles(e.target.files);
        input.value = "";
    });
}

async function uploadFiles(fileList) {
    const fileType = $("#uploadType").value;
    const progress = $("#uploadProgress");
    const fill = $("#uploadProgressFill");
    const text = $("#uploadProgressText");
    progress.style.display = "block";

    const files = Array.from(fileList);
    let done = 0;
    for (const file of files) {
        const pct = Math.round((done / files.length) * 100);
        fill.style.width = pct + "%";
        text.textContent = `上传中 (${done + 1}/${files.length})：${file.name}`;
        try {
            const fd = new FormData();
            fd.append("file", file);
            fd.append("file_type", fileType);
            const res = await api("/api/upload", { method: "POST", body: fd });
            toast(`${res.filename} 已上传`, "success", "上传成功");
            if (fileType === "resume" && res.resource_id && res.extraction) {
                await reviewUploadedResume(res);
            }
        } catch (e) {
            toast(`${file.name}：${e.message}`, "error", "上传失败");
        }
        done++;
    }
    fill.style.width = "100%";
    text.textContent = `完成 ${done}/${files.length}`;
    setTimeout(() => { progress.style.display = "none"; fill.style.width = "0%"; }, 1200);
    loadUploads();
    loadProfiles();
}

async function loadUploads() {
    const list = $("#fileList");
    list.innerHTML = '<div class="empty-state">加载中…</div>';
    try {
        const data = await api("/api/uploads");
        const uploads = data.uploads || [];
        if (!uploads.length) {
            list.innerHTML = '<div class="empty-state">暂无文件</div>';
            return;
        }
        list.innerHTML = "";
        uploads.forEach((u) => {
            const sizeText = formatSize(u.size);
            const timeText = u.modified_at || "";
            list.appendChild(
                el("div", { class: "file-item" }, [
                    el("div", { class: "file-icon", html: FILE_ICON_SVG }),
                    el("div", { class: "file-meta" }, [
                        el("div", { class: "file-name", text: u.filename }),
                        el("div", { class: "file-sub", text: `${sizeText} · ${timeText}` }),
                    ]),
                    el("span", { class: `badge badge-${u.file_type}`, text: u.file_type }),
                ])
            );
        });
    } catch (e) {
        list.innerHTML = `<div class="empty-state">加载失败：${escapeHtml(e.message)}</div>`;
    }
}

const FILE_ICON_SVG = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';

/* ---------------- 候选人档案（版本化、人工确认） ---------------- */
const PROFILE_FIELD_LABELS = {
    full_name: "姓名",
    name: "姓名",
    email: "邮箱",
    phone: "手机号",
    gender: "性别",
    address: "地址",
    education: "教育经历",
    work_experience: "工作经历",
    project_experience: "项目经历",
    skills: "技能",
    self_introduction: "自我介绍",
};

function extractionToFields(extraction) {
    const fields = {};
    (extraction.proposed_fields || extraction.fields || []).forEach((item) => {
        if (item.field_key) fields[item.field_key] = item.value ?? "";
    });
    return fields;
}

async function loadProfiles() {
    const container = $("#profileList");
    if (!container) return;
    container.innerHTML = '<div class="empty-state">加载中…</div>';
    try {
        const profiles = await api("/api/v2/profiles");
        state.profiles.items = profiles || [];
        if (!profiles.length) {
            state.profiles.selectedVersionId = null;
            container.innerHTML = '<div class="empty-state">尚未建立候选人档案，请在下方上传 PDF 简历并确认提取内容</div>';
            return;
        }
        const availableActiveIds = profiles.map((item) => item.active_version.id);
        if (!availableActiveIds.includes(state.profiles.selectedVersionId)) {
            state.profiles.selectedVersionId = profiles[0].active_version.id;
        }
        container.innerHTML = "";
        for (const profile of profiles) {
            const versions = await api(`/api/v2/profiles/${profile.id}/versions`);
            const active = profile.active_version;
            const title = active.fields.full_name || active.fields.name || `档案 ${profile.id.slice(0, 8)}`;
            const versionNodes = versions.map((version) => {
                const isActive = version.id === profile.active_version_id;
                const actions = [];
                if (!isActive && version.status !== "archived") {
                    actions.push(el("button", {
                        class: "btn btn-soft btn-sm",
                        text: "切换到此版本",
                        onclick: () => activateProfileVersion(profile, version),
                    }));
                }
                if (!isActive) {
                    actions.push(el("button", {
                        class: "btn btn-ghost btn-sm",
                        text: "删除",
                        onclick: () => deleteProfileVersion(profile, version),
                    }));
                }
                return el("div", { class: "file-item" }, [
                    el("div", { class: "file-meta" }, [
                        el("div", { class: "file-name", text: `版本 ${version.version_number}${isActive ? "（当前投递版本）" : ""}` }),
                        el("div", { class: "file-sub", text: `${formatTime(version.created_at)} · ${version.status}` }),
                    ]),
                    ...actions,
                ]);
            });
            container.appendChild(el("div", { style: "margin-bottom:18px" }, [
                el("div", { style: "display:flex;gap:10px;align-items:center;justify-content:space-between;margin-bottom:10px" }, [
                    el("div", {}, [
                        el("div", { class: "file-name", text: title }),
                        el("div", { class: "file-sub", text: `当前使用版本 ${active.version_number}；新投递将绑定该版本` }),
                    ]),
                    el("button", {
                        class: "btn btn-soft btn-sm",
                        text: "编辑并新建版本",
                        onclick: () => editProfileVersion(profile),
                    }),
                ]),
                ...versionNodes,
            ]));
        }
    } catch (e) {
        container.innerHTML = `<div class="empty-state">档案加载失败：${escapeHtml(e.message)}</div>`;
    }
}

function profileEditor(fields, { selectable = false } = {}) {
    const root = el("div", { style: "display:grid;gap:12px" });
    const keys = Object.keys(fields).filter((key) => !["resume_text", "raw_resume_text"].includes(key));
    if (!keys.length) keys.push("full_name", "email", "phone");
    keys.forEach((key) => {
        const value = fields[key] ?? "";
        const input = el("textarea", {
            class: "input profile-field-input",
            rows: String(value).length > 80 ? "5" : "2",
            "data-profile-key": key,
        });
        input.value = typeof value === "string" ? value : JSON.stringify(value, null, 2);
        const labelChildren = [];
        if (selectable) {
            const checkbox = el("input", { type: "checkbox", checked: "checked", "data-profile-select": key });
            checkbox.checked = true;
            labelChildren.push(checkbox);
        }
        labelChildren.push(document.createTextNode(` ${PROFILE_FIELD_LABELS[key] || key}`));
        root.appendChild(el("label", { style: "display:grid;gap:6px" }, [
            el("span", { class: "field-label" }, labelChildren),
            input,
        ]));
    });
    return root;
}

function readProfileEditor(root) {
    const fields = {};
    $$("[data-profile-key]", root).forEach((input) => {
        const key = input.dataset.profileKey;
        const raw = input.value.trim();
        if (/^[\[{]/.test(raw)) {
            try { fields[key] = JSON.parse(raw); return; } catch { /* keep text */ }
        }
        fields[key] = raw;
    });
    return fields;
}

async function reviewUploadedResume(upload) {
    const extracted = extractionToFields(upload.extraction);
    const profiles = await api("/api/v2/profiles");
    const profile = profiles[0] || null;
    const editor = profileEditor(extracted, { selectable: !!profile });
    const quality = upload.extraction.quality || {};
    const body = el("div", {}, [
        el("div", { class: "confirm-msg", text: profile
            ? "请选择这次 PDF 要增量更新的字段。确认后会建立独立版本，旧版本不会被覆盖。"
            : "请核对 PDF 提取内容。确认后才会建立第一个候选人档案版本。" }),
        el("div", { class: "file-sub", text: `页数 ${quality.page_count || 0} · 字符 ${quality.character_count || 0}${quality.needs_review ? " · 建议重点复核" : ""}` }),
        editor,
    ]);
    const confirm = el("button", { class: "btn btn-primary", text: profile ? "确认所选字段并新建版本" : "确认并建立档案" });
    confirm.addEventListener("click", async () => {
        confirm.disabled = true;
        try {
            const edited = readProfileEditor(editor);
            if (!profile) {
                await api("/api/v2/profiles", {
                    method: "POST",
                    json: { fields: edited, source_file_resource_id: upload.resource_id },
                });
            } else {
                const proposal = await api(`/api/v2/profiles/${profile.id}/change-proposals`, {
                    method: "POST",
                    json: {
                        base_version_id: profile.active_version_id,
                        source_file_resource_id: upload.resource_id,
                        proposed_fields: edited,
                    },
                });
                const selected = $$('[data-profile-select]:checked', editor).map((node) => node.dataset.profileSelect);
                await api(`/api/v2/change-proposals/${proposal.id}/accept`, {
                    method: "POST",
                    json: { selected_fields: Array.from(new Set(selected)), expected_version: profile.row_version },
                });
            }
            closeModal();
            toast("候选人档案版本已确认", "success", "档案已更新");
            await loadProfiles();
            loadUserInfoSummary();
        } catch (e) {
            toast(e.message, "error", "档案保存失败");
            confirm.disabled = false;
        }
    });
    openModal("核对 PDF 提取结果", body, el("div", { class: "confirm-options" }, [
        el("button", { class: "btn btn-ghost", text: "暂不建立", onclick: closeModal }),
        confirm,
    ]));
}

function editProfileVersion(profile) {
    const editor = profileEditor(profile.active_version.fields);
    const save = el("button", { class: "btn btn-primary", text: "保存为新版本" });
    save.addEventListener("click", async () => {
        save.disabled = true;
        try {
            const fields = readProfileEditor(editor);
            await api(`/api/v2/profiles/${profile.id}/versions`, {
                method: "POST",
                json: {
                    fields,
                    source_file_resource_id: profile.active_version.source_file_resource_id,
                    expected_version: profile.row_version,
                },
            });
            closeModal();
            toast("修改已保存为独立版本", "success");
            loadProfiles();
        } catch (e) {
            toast(e.message, "error", "保存失败");
            save.disabled = false;
        }
    });
    openModal("编辑候选人档案", editor, save);
}

async function activateProfileVersion(profile, version) {
    try {
        await api(`/api/v2/profiles/${profile.id}/versions/${version.id}/activate`, {
            method: "POST",
            json: { expected_version: profile.row_version },
        });
        state.profiles.selectedVersionId = version.id;
        toast(`已切换到版本 ${version.version_number}`, "success");
        loadProfiles();
        loadUserInfoSummary();
    } catch (e) { toast(e.message, "error", "切换失败"); }
}

async function deleteProfileVersion(profile, version) {
    if (!confirm(`确定删除版本 ${version.version_number}？该操作不可撤销。`)) return;
    try {
        await api(`/api/v2/profiles/${profile.id}/versions/${version.id}?expected_version=${profile.row_version}`, { method: "DELETE" });
        toast(`版本 ${version.version_number} 已删除`, "success");
        loadProfiles();
    } catch (e) { toast(e.message, "error", "删除失败"); }
}

/* ---------------- Agent 临时连接 ---------------- */
function loadSavedAgentApiSettings() {
    try {
        const raw = localStorage.getItem(API_SETTINGS_STORAGE_KEY);
        if (!raw) return null;
        const saved = JSON.parse(raw);
        if (!saved.api_base_url || !saved.api_key || !saved.model_name) return null;
        return saved;
    } catch {
        return null;
    }
}

function saveAgentApiSettingsToBrowser(payload) {
    try {
        localStorage.setItem(API_SETTINGS_STORAGE_KEY, JSON.stringify(payload));
        return true;
    } catch {
        return false;
    }
}

function forgetSavedAgentApiSettings() {
    localStorage.removeItem(API_SETTINGS_STORAGE_KEY);
}

function renderAgentApiStatus(status, mode = "") {
    const box = $("#apiConnectionStatus");
    const verified = !!status.verified;
    state.agentApi.verified = verified;
    box.className = `api-connection-status ${mode || (verified ? "verified" : "idle")}`;

    if (mode === "testing") {
        $("#apiStatusTitle").textContent = "正在验证 Agent 连接…";
        $("#apiStatusDetail").textContent = "正在向所选模型发送一个最小测试请求。";
    } else if (mode === "error") {
        $("#apiStatusTitle").textContent = "连接验证失败";
        $("#apiStatusDetail").textContent = status.message || "请检查接口地址、密钥和模型名称。";
    } else if (verified) {
        $("#apiStatusTitle").textContent = "Agent 连接已验证";
        $("#apiStatusDetail").textContent =
            `${status.model_name || "模型"} · ${status.api_base_url || ""}` +
            (status.verified_at ? ` · ${formatTime(status.verified_at)}` : "") +
            ($("#rememberApiSettings").checked
                ? "。已保存在此浏览器，服务重启后会自动重新验证。"
                : "。配置仅在本次服务运行期间有效。");
    } else if (status.last_error) {
        box.className = "api-connection-status error";
        $("#apiStatusTitle").textContent = "上次连接验证失败";
        $("#apiStatusDetail").textContent = status.last_error;
    } else {
        $("#apiStatusTitle").textContent = "尚未验证连接";
        $("#apiStatusDetail").textContent = "请输入接口地址、模型和密钥，然后点击“验证并启用”。";
    }

    const badge = $("#agentApiBadge");
    badge.style.display = verified ? "none" : "";
}

async function loadAgentApiSettings() {
    try {
        const s = await api("/api/settings/api");
        const saved = loadSavedAgentApiSettings();
        if (saved) {
            $("#apiBaseUrl").value = saved.api_base_url;
            $("#apiModel").value = saved.model_name;
            $("#apiKey").value = s.verified ? "" : saved.api_key;
            $("#rememberApiSettings").checked = true;
        } else {
            $("#apiBaseUrl").value = s.api_base_url || "";
            $("#apiModel").value = s.model_name || "";
            $("#apiKey").value = "";
            $("#rememberApiSettings").checked = false;
        }
        renderAgentApiStatus(s);
        if (
            !s.verified &&
            saved &&
            !state.agentApi.autoVerifyAttempted
        ) {
            state.agentApi.autoVerifyAttempted = true;
            await verifyAgentApiSettings({ automatic: true });
        }
    } catch (e) {
        renderAgentApiStatus({ verified: false, message: e.message }, "error");
        toast(e.message, "error", "加载 Agent 连接状态失败");
    }
}

async function verifyAgentApiSettings({ automatic = false } = {}) {
    const payload = {
        api_base_url: $("#apiBaseUrl").value.trim(),
        api_key: $("#apiKey").value.trim(),
        model_name: $("#apiModel").value.trim(),
    };
    if (!payload.api_base_url || !payload.api_key || !payload.model_name) {
        toast("接口地址、API 密钥和模型名称均不能为空", "warning", "无法验证");
        return;
    }

    const btn = $("#verifyApiSettingsBtn");
    btn.disabled = true;
    renderAgentApiStatus({ verified: false }, "testing");
    try {
        const result = await api("/api/settings/api/verify", {
            method: "POST",
            json: payload,
        });
        if ($("#rememberApiSettings").checked) {
            if (!saveAgentApiSettingsToBrowser(payload)) {
                $("#rememberApiSettings").checked = false;
                toast(
                    "浏览器拒绝写入本地存储；Agent 已连接，但配置未保存",
                    "warning",
                    "未能保存"
                );
            }
        } else {
            forgetSavedAgentApiSettings();
        }
        $("#apiKey").value = "";
        renderAgentApiStatus({
            verified: true,
            api_base_url: result.api_base_url,
            model_name: result.model_name,
            verified_at: result.verified_at,
        });
        toast(
            automatic ? "已使用浏览器中保存的配置自动连接 Agent" : result.message,
            "success",
            "连接成功"
        );
    } catch (e) {
        renderAgentApiStatus({ verified: false, message: e.message }, "error");
        toast(e.message, "error", "连接失败");
    } finally {
        btn.disabled = false;
    }
}

async function clearAgentApiSettings() {
    try {
        const status = await api("/api/settings/api", { method: "DELETE" });
        forgetSavedAgentApiSettings();
        state.agentApi.autoVerifyAttempted = false;
        $("#apiKey").value = "";
        $("#rememberApiSettings").checked = false;
        $("#apiBaseUrl").value = status.api_base_url || "https://api.openai.com/v1";
        $("#apiModel").value = status.model_name || "gpt-4o";
        renderAgentApiStatus(status);
        toast("Agent API 配置已从服务内存和当前浏览器中清除", "success");
    } catch (e) {
        toast(e.message, "error", "清除失败");
    }
}

async function ensureAgentApiVerified() {
    try {
        const status = await api("/api/settings/api");
        renderAgentApiStatus(status);
        if (status.verified) return true;
    } catch (e) {
        toast(e.message, "error", "无法检查 Agent 连接");
        return false;
    }
    switchView("agent-api");
    toast("请先输入 API 配置并验证 Agent 连接", "warning", "尚未连接");
    return false;
}

/* ---------------- 通知设置 ---------------- */
async function loadSettings() {
    try {
        const s = await api("/api/settings/notifications");
        $("#emailEnabled").checked = !!s.email_enabled;
        $("#smtpServer").value = s.smtp_server || "";
        $("#smtpPort").value = s.smtp_port || "";
        $("#smtpUseTls").checked = !!s.smtp_use_tls;
        $("#smtpSenderEmail").value = s.smtp_sender_email || "";
        $("#smtpSenderPassword").value = s.smtp_sender_password || "";
        $("#smtpRecipientEmail").value = s.smtp_recipient_email || "";
    } catch (e) {
        toast(e.message, "error", "加载设置失败");
    }
}

async function saveSettings() {
    const payload = {
        email_enabled: $("#emailEnabled").checked,
        smtp_server: $("#smtpServer").value.trim(),
        smtp_port: parseInt($("#smtpPort").value, 10) || 587,
        smtp_use_tls: $("#smtpUseTls").checked,
        smtp_sender_email: $("#smtpSenderEmail").value.trim(),
        smtp_sender_password: $("#smtpSenderPassword").value,
        smtp_recipient_email: $("#smtpRecipientEmail").value.trim(),
    };
    const btn = $("#saveSettingsBtn");
    btn.disabled = true;
    try {
        await api("/api/settings/notifications", { method: "PUT", json: payload });
        toast("设置已保存", "success");
    } catch (e) {
        toast(e.message, "error", "保存失败");
    } finally {
        btn.disabled = false;
    }
}

/* ---------------- 记忆管理 ---------------- */
async function loadMemory() {
    const tbody = $("#memoryTableBody");
    tbody.innerHTML = '<tr><td colspan="6" class="empty-state">加载中…</td></tr>';
    try {
        const data = await api("/api/memory");
        const learned = data.learned_fields || {};
        const source = data.source_user_info || {};
        const meta = data.field_metadata || {};

        const allKeys = new Set([...Object.keys(learned), ...Object.keys(source)]);
        if (!allKeys.size) {
            tbody.innerHTML = '<tr><td colspan="6" class="empty-state">暂无记忆数据</td></tr>';
            return;
        }

        tbody.innerHTML = "";
        allKeys.forEach((k) => {
            const isLearned = k in learned;
            const value = isLearned ? learned[k] : source[k];
            const m = meta[k] || {};
            const sourceLabel = isLearned
                ? '<span class="source-tag source-learned">补充</span>'
                : '<span class="source-tag source-source">原始</span>';
            const valueText = typeof value === "object"
                ? JSON.stringify(value)
                : String(value ?? "");
            const tr = el("tr", {}, [
                el("td", { class: "field-name", text: k }),
                el("td", { class: "field-value", text: valueText }),
                el("td", { class: "field-source", html: sourceLabel }),
                el("td", { class: "field-time", text: formatTime(m.timestamp) }),
                el("td", { text: m.reason || "—" }),
                el("td", {}, isLearned
                    ? [el("button", {
                        class: "btn btn-outline-danger btn-sm",
                        text: "删除",
                        onclick: () => deleteMemory(k),
                    })]
                    : [el("span", { class: "field-source", text: "—" })]
                ),
            ]);
            tbody.appendChild(tr);
        });
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="6" class="empty-state">加载失败：${escapeHtml(e.message)}</td></tr>`;
    }
}

async function deleteMemory(fieldName) {
    if (!confirm(`确认删除字段「${fieldName}」？`)) return;
    try {
        await api(`/api/memory/${encodeURIComponent(fieldName)}`, { method: "DELETE" });
        toast(`已删除 ${fieldName}`, "success");
        loadMemory();
    } catch (e) {
        toast(e.message, "error", "删除失败");
    }
}

/* ---------------- WebSocket ---------------- */
function setConnStatus(state_) {
    const pill = $("#connPill");
    const text = $("#connText");
    pill.classList.remove("connected", "connecting", "error");
    if (state_ === "connected") {
        pill.classList.add("connected");
        text.textContent = "已连接";
    } else if (state_ === "connecting") {
        pill.classList.add("connecting");
        text.textContent = "连接中…";
    } else if (state_ === "error") {
        pill.classList.add("error");
        text.textContent = "连接错误";
    } else {
        text.textContent = "未连接";
    }
}

function isTerminalSessionStatus(status) {
    return ["completed", "error", "cancelled"].includes(status);
}

function connectWebSocket(sessionId) {
    setConnStatus("connecting");
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws/sessions/${sessionId}`;

    let ws;
    try {
        ws = new WebSocket(url);
    } catch (e) {
        setConnStatus("error");
        toast("WebSocket 创建失败", "error");
        return;
    }
    state.session.ws = ws;

    ws.onopen = () => {
        setConnStatus("connected");
        addLog("success", `WebSocket 已连接 (session=${sessionId})`);
    };
    ws.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch { return; }
        handleWsMessage(msg);
    };
    ws.onclose = () => {
        setConnStatus(isTerminalSessionStatus(state.session.status) ? "connected" : "error");
        if (!isTerminalSessionStatus(state.session.status)) {
            addLog("warning", "WebSocket 已断开，尝试重连…");
            scheduleReconnect(sessionId);
        } else {
            addLog("info", "WebSocket 已关闭");
        }
    };
    ws.onerror = () => {
        setConnStatus("error");
    };
}

function scheduleReconnect(sessionId) {
    if (state.session.wsReconnectTimer) return;
    state.session.wsReconnectTimer = setTimeout(() => {
        state.session.wsReconnectTimer = null;
        if (isTerminalSessionStatus(state.session.status)) return;
        connectWebSocket(sessionId);
    }, 2500);
}

function sendWsResponse(requestId, data) {
    const ws = state.session.ws;
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "response", request_id: requestId, data }));
        return true;
    }
    // 回退到 REST
    return false;
}

async function sendResponseRest(sessionId, requestId, responseType, data) {
    try {
        await api(`/api/sessions/${sessionId}/confirm`, {
            method: "POST",
            json: { request_id: requestId, response_type: responseType, data },
        });
        return true;
    } catch (e) {
        toast(e.message, "error", "响应失败");
        return false;
    }
}

/* ---------------- WebSocket 消息处理 ---------------- */
function handleWsMessage(msg) {
    switch (msg.type) {
        case "progress":
            handleProgress(msg);
            break;
        case "screenshot":
            handleScreenshot(msg);
            break;
        case "log":
            addLog(msg.level || "info", msg.message || "");
            break;
        case "request":
            handleRequest(msg);
            break;
        case "result":
            handleResult(msg);
            break;
        case "session_complete":
            handleSessionComplete(msg);
            break;
        case "session_cancelled":
            handleSessionCancelled(msg);
            break;
        case "error":
            addLog("error", msg.message || "未知错误");
            toast(msg.message || "错误", "error", "Agent 错误");
            if (msg.message === "会话不存在") {
                updateSessionStatus("error");
                if (state.session.wsReconnectTimer) {
                    clearTimeout(state.session.wsReconnectTimer);
                    state.session.wsReconnectTimer = null;
                }
            }
            break;
        case "agent_message":
            state.chat.messages.push({
                role: "agent",
                content: msg.content || "",
                time: nowTimeStr(),
            });
            renderChatMessages();
            addLog("info", `[对话] Agent：${msg.content || ""}`);
            break;
        case "message_status":
            // 显示消息状态（queued/restarted 等）
            if (msg.status) {
                addLog("info", `[对话] 消息状态：${msg.status}${msg.message ? " - " + msg.message : ""}`);
            }
            break;
        default:
            console.debug("未处理的消息类型", msg);
    }
}

function handleProgress(msg) {
    const phase = msg.phase;
    const company = msg.company || "";
    const message = msg.message || "";
    if (state.session.status !== "running") {
        updateSessionStatus("running");
    }

    // 全局阶段更新
    if (phase && PHASE_INDEX[phase] !== undefined) {
        if (state.session.phase && PHASE_INDEX[state.session.phase] < PHASE_INDEX[phase]) {
            state.session.completedPhases.add(state.session.phase);
        }
        state.session.phase = phase;
    }

    // 公司级状态更新
    if (company && state.session.companies[company]) {
        const c = state.session.companies[company];
        c.phase = phase || c.phase;
        c.message = message;
        if (phase === "submit") {
            c.submitted = true;
            c.status = "completed";
        } else if (phase === "fill") {
            c.form_filled = true;
            c.status = "running";
        } else if (phase) {
            c.status = "running";
        }
    }

    addLog("info", `[${company || "全局"}] ${phaseLabel(phase)} ${message}`);
    renderTimeline();
    renderCompanyCards();
}

function phaseLabel(phase) {
    if (!phase) return "";
    const p = PHASES.find((x) => x.key === phase);
    return p ? p.label : phase;
}

function handleScreenshot(msg) {
    const card = $("#screenshotCard");
    card.style.display = "block";
    const grid = $("#screenshotGrid");
    const item = el("div", { class: "screenshot-item" }, [
        el("div", {
            class: "screenshot-thumb",
            html: SCREENSHOT_PLACEHOLDER,
        }),
        el("div", { class: "screenshot-meta" }, [
            el("div", { class: "company", text: msg.company || "未知公司" }),
            el("div", { class: "path", text: msg.path || "", title: msg.path || "" }),
        ]),
    ]);
    grid.insertBefore(item, grid.firstChild);
    addLog("info", `[${msg.company || ""}] 截图：${msg.path || ""}`);
}

const SCREENSHOT_PLACEHOLDER = '<svg viewBox="0 0 24 24" width="36" height="36" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>';

function handleResult(msg) {
    const company = msg.company || "";
    if (company && state.session.companies[company]) {
        const r = msg.result || {};
        state.session.companies[company].status = r.submitted ? "completed" : "error";
        state.session.companies[company].submitted = !!r.submitted;
        state.session.companies[company].form_filled = !!r.form_filled;
        if (r.error || r.error_message) {
            state.session.companies[company].error = r.error || r.error_message;
        }
    }
    addLog("success", `[${company}] 投递结果：${JSON.stringify(msg.result || {})}`);
    renderCompanyCards();
}

function handleSessionComplete(msg) {
    state.session.results = msg.results || {};
    const companyResults = Object.values(state.session.results).filter((item) => item && typeof item === "object");
    const failed = companyResults.filter((item) => item.status === "error");
    Object.entries(state.session.results).forEach(([company, result]) => {
        if (!state.session.companies[company] || !result || typeof result !== "object") return;
        const target = state.session.companies[company];
        target.status = result.status === "error" ? "error" : (result.submitted ? "completed" : result.status || "completed");
        target.form_filled = !!result.form_filled;
        target.submitted = !!result.submitted;
        target.error = result.error || "";
    });
    if (failed.length) {
        state.session.status = "error";
        updateSessionStatus("error");
        addLog("error", `会话结束，但有 ${failed.length} 家公司执行失败`);
        toast(failed[0].error || "公司流程执行失败", "error", "会话失败");
    } else {
        state.session.status = "completed";
        updateSessionStatus("completed");
        addLog("success", "会话已完成");
        toast("投递会话已完成", "success", "完成");
    }

    const card = $("#resultCard");
    card.style.display = "block";
    $("#resultPre").textContent = JSON.stringify(msg.results, null, 2);
    renderCompanyCards();
}

function handleSessionCancelled(msg) {
    if (state.session.status === "cancelled") return;
    state.session.status = "cancelled";
    updateSessionStatus("cancelled");
    addLog("warning", msg.message || "任务已停止");
    toast(msg.message || "任务已停止", "warning", "已中断");
}

/* ---------------- 监控视图渲染 ---------------- */
function initMonitor() {
    $("#monitorEmpty").style.display = "none";
    $("#monitorWrap").style.display = "block";
    $("#screenshotCard").style.display = "none";
    $("#screenshotGrid").innerHTML = "";
    $("#resultCard").style.display = "none";
    $("#resultPre").textContent = "";
    $("#logPanel").innerHTML = '<div class="log-empty">等待日志…</div>';

    // 重置对话区域
    state.chat.messages = [];
    renderChatMessages();

    // 会话元信息
    const meta = $("#sessionMeta");
    meta.textContent = `会话 ID：${state.session.id}`;

    updateSessionStatus(state.session.status || "pending");
    renderTimeline();
    renderCompanyCards();
}

function updateSessionStatus(status) {
    state.session.status = status;
    const map = {
        pending: { text: "等待中", cls: "status-pending" },
        running: { text: "运行中", cls: "status-running" },
        completed: { text: "已完成", cls: "status-completed" },
        error: { text: "出错", cls: "status-error" },
        disconnected: { text: "已断开", cls: "status-disconnected" },
        cancelled: { text: "已停止", cls: "status-disconnected" },
    };
    const m = map[status] || map.pending;
    $("#sessionStatus").innerHTML = `<span class="status-badge ${m.cls}">${m.text}</span>`;
    // 中断/停止按钮：搜索阶段进入 running 后立即显示
    const interruptBtn = $("#interruptBtn");
    if (interruptBtn) {
        interruptBtn.style.display = status === "running" ? "inline-flex" : "none";
    }
    const stopBtn = $("#stopSessionBtn");
    if (stopBtn) {
        stopBtn.style.display = ["pending", "running"].includes(status) ? "inline-flex" : "none";
    }
}

function renderTimeline() {
    const tl = $("#phaseTimeline");
    tl.innerHTML = "";
    const currentIdx = state.session.phase ? PHASE_INDEX[state.session.phase] : -1;
    PHASES.forEach((p, i) => {
        let cls = "";
        if (currentIdx >= 0) {
            if (i < currentIdx || state.session.completedPhases.has(p.key)) cls = "done";
            else if (i === currentIdx) cls = "current";
        }
        const node = el("div", { class: `phase ${cls}` }, [
            el("div", { class: "phase-node", text: i + 1 }),
            el("div", { class: "phase-label", text: p.label }),
        ]);
        tl.appendChild(node);
    });
}

function renderCompanyCards() {
    const wrap = $("#companyCards");
    const companies = state.session.companies;
    const names = Object.keys(companies);
    if (!names.length) {
        wrap.innerHTML = '<div class="empty-state">暂无公司</div>';
        return;
    }
    wrap.innerHTML = "";
    names.forEach((name) => {
        const c = companies[name];
        const cls = c.status || "pending";
        const card = el("div", { class: `company-card ${cls}` }, [
            el("div", { class: "company-card-head" }, [
                el("div", { class: "company-name", text: name }),
                el("span", { class: `status-badge status-${cls}` }, [
                    el("span", { text: STATUS_TEXT[c.status] || c.status || "等待中" }),
                ]),
            ]),
            el("div", { class: "company-card-meta" }, [
                el("span", { class: `meta-chip ${c.form_filled ? "ok" : "no"}`, text: `填表 ${c.form_filled ? "✓" : "✗"}` }),
                el("span", { class: `meta-chip ${c.submitted ? "ok" : "no"}`, text: `投递 ${c.submitted ? "✓" : "✗"}` }),
                c.phase ? el("span", { class: "meta-chip", text: `阶段：${phaseLabel(c.phase)}` }) : null,
            ]),
            c.message ? el("div", { class: "company-current-phase", text: c.message }) : null,
            c.error ? el("div", { class: "company-error", text: c.error }) : null,
        ]);
        wrap.appendChild(card);
    });
}

const STATUS_TEXT = {
    pending: "等待中",
    running: "运行中",
    completed: "已完成",
    error: "出错",
    disconnected: "已断开",
};

/* ---------------- 日志面板 ---------------- */
function addLog(level, message) {
    const panel = $("#logPanel");
    const empty = panel.querySelector(".log-empty");
    if (empty) empty.remove();

    const line = el("div", { class: `log-line ${level || "info"}` }, [
        el("span", { class: "log-time", text: nowTimeStr() }),
        el("span", { class: `log-tag ${level || "info"}`, text: (level || "info").toUpperCase() }),
        el("span", { class: "log-msg", text: message }),
    ]);
    panel.appendChild(line);
    panel.scrollTop = panel.scrollHeight;

    // 限制日志条数
    while (panel.children.length > 500) panel.removeChild(panel.firstChild);
}

/* ---------------- 对话区域 ---------------- */
function renderChatMessages() {
    const container = $("#chatMessages");
    if (!container) return;
    container.innerHTML = "";
    if (!state.chat.messages.length) {
        container.innerHTML = '<div class="chat-empty">暂无对话，可在下方输入消息指导 Agent</div>';
        return;
    }
    state.chat.messages.forEach((m) => {
        const isUser = m.role === "user";
        const node = el("div", { class: isUser ? "chat-msg-user" : "chat-msg-agent" }, [
            el("div", { class: "chat-msg-content", text: m.content }),
            m.time ? el("div", { class: "chat-msg-time", text: m.time }) : null,
        ]);
        container.appendChild(node);
    });
    // 滚动到底部
    container.scrollTop = container.scrollHeight;
}

function sendChatMessage(text) {
    text = (text || "").trim();
    if (!text) return;
    if (!state.session.id) {
        toast("请先启动投递任务", "warning", "无法发送");
        return;
    }
    const ws = state.session.ws;
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "user_message", message: text }));
    } else {
        // WebSocket 未连接，回退到 REST
        api(`/api/sessions/${state.session.id}/message`, {
            method: "POST",
            json: { message: text },
        }).catch((e) => {
            toast(e.message, "error", "发送失败");
            addLog("error", `消息发送失败：${e.message}`);
        });
    }
    state.chat.messages.push({
        role: "user",
        content: text,
        time: nowTimeStr(),
    });
    renderChatMessages();
    addLog("info", `[对话] 用户：${text}`);
    const input = $("#chatInput");
    if (input) input.value = "";
}

function interruptAgent(text) {
    text = (text || "").trim();
    if (!state.session.id) {
        toast("请先启动投递任务", "warning", "无法中断");
        return;
    }
    const ws = state.session.ws;
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "interrupt", message: text }));
    } else {
        // WebSocket 未连接，回退到 REST
        api(`/api/sessions/${state.session.id}/interrupt`, {
            method: "POST",
            json: { message: text },
        }).catch((e) => {
            toast(e.message, "error", "中断失败");
            addLog("error", `中断请求失败：${e.message}`);
        });
    }
    state.chat.messages.push({
        role: "user",
        content: `[中断并重试] ${text}`,
        time: nowTimeStr(),
    });
    renderChatMessages();
    addLog("warning", `[对话] 用户中断并重试：${text}`);
}

async function stopCurrentSession() {
    if (!state.session.id) {
        toast("当前没有可停止的任务", "warning");
        return;
    }
    if (!confirm("确定立即停止当前任务吗？停止后不会自动重启。")) return;

    const btn = $("#stopSessionBtn");
    btn.disabled = true;
    try {
        const result = await api(`/api/sessions/${state.session.id}/cancel`, {
            method: "POST",
        });
        handleSessionCancelled({ message: "任务已由用户停止" });
        if (state.session.ws) {
            state.session.ws.close();
            state.session.ws = null;
        }
        addLog("warning", `停止结果：${result.status || "cancelled"}`);
    } catch (e) {
        toast(e.message, "error", "停止失败");
    } finally {
        btn.disabled = false;
    }
}

/* ---------------- HITL 请求处理 ---------------- */
function handleRequest(msg) {
    const reqType = msg.request_type;
    const requestId = msg.request_id;
    addLog("info", `收到人工请求：${reqType} (id=${requestId})`);

    // 监控徽章提示
    const badge = $("#monitorBadge");
    badge.style.display = "inline-flex";
    badge.textContent = "!";

    switch (reqType) {
        case "confirmation":
            showConfirmation(msg);
            break;
        case "missing_fields":
            showMissingFields(msg);
            break;
        case "resume_review":
            showResumeReview(msg);
            break;
        case "position_selection":
            showPositionSelection(msg);
            break;
        case "user_login":
            showLoginRequestPanel(msg);
            break;
        default:
            console.warn("未知请求类型", reqType, msg);
            toast(`未知请求类型：${reqType}`, "warning");
    }
}

function openModal(title, bodyNode, footerNode) {
    $("#modalTitle").textContent = title;
    const body = $("#modalBody");
    body.innerHTML = "";
    if (bodyNode) body.appendChild(bodyNode);
    const footer = $("#modalFooter");
    footer.innerHTML = "";
    if (footerNode) footer.appendChild(footerNode);
    $("#modalMask").classList.add("open");
}

function closeModal() {
    $("#modalMask").classList.remove("open");
    // 清除徽章（如果已无更多挂起请求）
    const badge = $("#monitorBadge");
    badge.style.display = "none";
}

function respond(requestId, responseType, data) {
    const ok = sendWsResponse(requestId, data);
    if (ok) {
        addLog("success", `已响应请求 ${requestId}`);
        closeModal();
    } else {
        // 回退到 REST
        addLog("info", `WebSocket 不可用，使用 REST 响应 ${requestId}`);
        sendResponseRest(state.session.id, requestId, responseType, data).then((ok2) => {
            if (ok2) closeModal();
        });
    }
}

/* —— confirmation —— */
function showConfirmation(msg) {
    const options = msg.options || [];
    const body = el("div", {}, [
        el("div", { class: "confirm-msg", text: msg.message || "" }),
    ]);
    const footer = el("div", { class: "confirm-options" }, options.map((opt) =>
        el("button", {
            class: "btn btn-soft",
            text: opt,
            onclick: () => respond(msg.request_id, "confirmation", { selected: opt }),
        })
    ));
    openModal(msg.title || "请确认", body, footer);
}

/* —— missing_fields —— */
function showMissingFields(msg) {
    const fields = msg.fields || [];
    const body = el("div", {});
    const inputs = {};

    fields.forEach((f) => {
        const name = f.name || "";
        const label = f.label || name;
        const reason = f.reason || "";
        const group = el("div", { class: "hform-field" }, [
            el("label", { class: "field-label", text: label }),
            el("input", {
                class: "input",
                type: "text",
                placeholder: `请输入${label}`,
                oninput: (e) => { inputs[name] = e.target.value; },
            }),
            reason ? el("div", { class: "reason", text: `原因：${reason}` }) : null,
        ]);
        body.appendChild(group);
    });

    const footer = el("div", {}, [
        el("button", {
            class: "btn btn-primary",
            text: "提交",
            onclick: () => {
                // 校验
                const missing = fields.filter((f) => !inputs[f.name]);
                if (missing.length) {
                    toast(`请填写：${missing.map((m) => m.label || m.name).join("、")}`, "warning");
                    return;
                }
                respond(msg.request_id, "missing_fields", { fields: inputs });
            },
        }),
        el("button", { class: "btn btn-ghost", text: "取消", onclick: closeModal }),
    ]);
    openModal("需要补充字段", body, footer);
}

/* —— resume_review —— */
function showResumeReview(msg) {
    const original = msg.original || {};
    const polished = msg.polished || {};
    const sourceResumeText = String(original.source_resume_text || "").trim();
    const sourceResumeFile = String(original.source_resume_file || "").trim();
    const editable = JSON.parse(JSON.stringify(polished));

    const body = el("div", {}, [
        el("p", {
            style: "margin: 0 0 12px; font-size: 13px; color: var(--gray-600);",
            text: sourceResumeText
                ? "左侧是上传简历的原始文本，也是本次润色的唯一简历依据；右侧可编辑后提交。"
                : "对比原始与润色后的简历内容。可在右侧编辑后提交，或直接采用润色版本。",
        }),
    ]);

    const compare = el("div", { class: "resume-compare" });

    // 原始列
    const origCol = el("div", { class: "resume-col" }, [
        el("h4", { text: sourceResumeText ? "原始内容（上传简历）" : "原始内容" }),
    ]);
    // 润色列
    const polCol = el("div", { class: "resume-col polished" }, [el("h4", { text: "润色内容（可编辑）" })]);

    if (sourceResumeText) {
        origCol.appendChild(
            el("div", { class: "resume-source-card" }, [
                el("div", {
                    class: "resume-section-label",
                    text: sourceResumeFile
                        ? `上传简历原文 · ${sourceResumeFile}`
                        : "上传简历原文",
                }),
                el("div", {
                    class: "resume-source-text",
                    text: sourceResumeText,
                }),
            ])
        );
    }

    Object.keys(RESUME_LABELS).forEach((key) => {
        const origVal = original[key];
        const polVal = polished[key];

        // 原始
        if (!sourceResumeText) {
            origCol.appendChild(
                el("div", { class: "resume-section" }, [
                    el("div", { class: "resume-section-label", text: RESUME_LABELS[key] }),
                    el("div", {
                        class: "resume-section-value",
                        text: formatResumeValue(origVal) || "—",
                    }),
                ])
            );
        }

        const section = el("div", { class: "resume-section" }, [
            el("div", { class: "resume-section-label", text: RESUME_LABELS[key] }),
        ]);
        if (Array.isArray(polVal)) {
            editable[key] = editable[key] || [];
            const list = el("div", { style: "display:grid;gap:10px" });
            const renderItems = () => {
                list.innerHTML = "";
                const items = editable[key];
                if (!items.length) {
                    list.appendChild(el("div", { class: "file-sub", text: "没有从原始简历中确认到这一类经历" }));
                }
                items.forEach((item, index) => {
                    const fields = RESUME_ARRAY_FIELDS[key] || [];
                    const card = el("div", { style: "border:1px solid var(--gray-200);border-radius:10px;padding:10px;display:grid;gap:8px;background:#fff" }, [
                        el("div", { style: "display:flex;justify-content:space-between;align-items:center" }, [
                            el("strong", { text: `${RESUME_LABELS[key]} ${index + 1}` }),
                            el("button", {
                                class: "btn btn-ghost btn-sm",
                                text: "删除此项",
                                onclick: () => { items.splice(index, 1); renderItems(); },
                            }),
                        ]),
                    ]);
                    fields.forEach(([field, label]) => {
                        const longField = ["description", "relevance", "relevance_to_jd"].includes(field);
                        const input = el(longField ? "textarea" : "input", {
                            class: longField ? "" : "input",
                            rows: longField ? "3" : null,
                            placeholder: label,
                        });
                        input.value = item[field] || "";
                        input.addEventListener("input", () => { item[field] = input.value; });
                        card.appendChild(el("label", { style: "display:grid;gap:4px" }, [
                            el("span", { class: "file-sub", text: label }),
                            input,
                        ]));
                    });
                    list.appendChild(card);
                });
                const add = el("button", { class: "btn btn-soft btn-sm", text: "添加一项" });
                add.addEventListener("click", () => {
                    const empty = {};
                    (RESUME_ARRAY_FIELDS[key] || []).forEach(([field]) => { empty[field] = ""; });
                    editable[key].push(empty);
                    renderItems();
                });
                list.appendChild(add);
            };
            renderItems();
            section.appendChild(list);
        } else {
            const textarea = el("textarea", {
                rows: key === "self_introduction" || key === "summary" ? 4 : 5,
            });
            textarea.value = polVal || "";
            textarea.addEventListener("input", () => { editable[key] = textarea.value; });
            section.appendChild(textarea);
        }
        polCol.appendChild(section);
    });

    compare.appendChild(origCol);
    compare.appendChild(polCol);
    body.appendChild(compare);

    const footer = el("div", {}, [
        el("button", {
            class: "btn btn-ghost",
            text: "直接采用润色版",
            onclick: () => respond(msg.request_id, "resume_review", { confirmed: polished }),
        }),
        el("button", {
            class: "btn btn-primary",
            text: "提交编辑后内容",
            onclick: () => {
                respond(msg.request_id, "resume_review", { confirmed: editable });
            },
        }),
        el("button", { class: "btn btn-ghost", text: "取消", onclick: closeModal }),
    ]);
    openModal("简历润色审核", body, footer);
}

function formatResumeValue(val) {
    if (val == null) return "";
    if (typeof val === "string") return val;
    if (Array.isArray(val)) {
        return val.map((item) =>
            typeof item === "object" ? JSON.stringify(item, null, 2) : String(item)
        ).join("\n");
    }
    if (typeof val === "object") return JSON.stringify(val, null, 2);
    return String(val);
}

/* —— position_selection —— */
function showPositionSelection(msg) {
    const positions = msg.positions || [];
    const selected = []; // [{position, order}]

    const body = el("div", {}, [
        el("p", {
            style: "margin: 0 0 12px; font-size: 13px; color: var(--gray-600);",
            text: "选择要投递的岗位。点击岗位卡片选择/取消，再次点击调整志愿顺序。",
        }),
    ]);
    const list = el("div", { class: "position-list" });
    body.appendChild(list);

    function render() {
        list.innerHTML = "";
        positions.forEach((pos, idx) => {
            const orderIdx = selected.findIndex((s) => s.__idx === idx);
            const isSelected = orderIdx >= 0;
            const order = orderIdx >= 0 ? orderIdx + 1 : null;

            const item = el("div", { class: `position-item ${isSelected ? "selected" : ""}` }, [
                el("div", { class: "position-order", text: order || idx + 1 }),
                el("div", { class: "position-body" }, [
                    el("div", { class: "position-name", text: pos.name || pos.title || `岗位 ${idx + 1}` }),
                    pos.location ? el("div", { class: "position-meta", text: `地点：${pos.location}` }) : null,
                    pos.reason ? el("div", { class: "position-reason", text: `推荐理由：${pos.reason}` }) : null,
                    pos.jd ? el("div", { class: "position-jd", text: pos.jd }) : null,
                ]),
                el("div", { class: "position-actions" }, [
                    el("button", {
                        class: `btn ${isSelected ? "btn-outline-danger" : "btn-soft"} btn-sm`,
                        text: isSelected ? "移除" : "选择",
                        onclick: (e) => {
                            e.stopPropagation();
                            if (isSelected) {
                                selected.splice(orderIdx, 1);
                            } else {
                                selected.push({ ...pos, __idx: idx });
                            }
                            render();
                        },
                    }),
                ]),
            ]);
            list.appendChild(item);
        });
    }
    render();

    const footer = el("div", {}, [
        el("span", {
            style: "margin-right: auto; align-self: center; font-size: 12px; color: var(--gray-600);",
            text: `已选 ${selected.length} 个岗位`,
        }),
        el("button", {
            class: "btn btn-primary",
            text: "提交选择",
            onclick: () => {
                if (!selected.length) {
                    toast("请至少选择一个岗位", "warning");
                    return;
                }
                const payload = selected.map((s, i) => {
                    const copy = { ...s };
                    delete copy.__idx;
                    copy.volunteer_order = i + 1;
                    return copy;
                });
                respond(msg.request_id, "position_selection", { selected_positions: payload });
            },
        }),
        el("button", { class: "btn btn-ghost", text: "取消", onclick: closeModal }),
    ]);
    openModal("选择投递岗位", body, footer);
}

/* —— user_login —— */
function showLoginRequestPanel(msg) {
    const loginUrl = msg.login_url || "";
    const message = msg.message || "";
    const isFormRecovery = ["application_form", "application_form_wait"].includes(msg.mode);
    const isCurrentPageWait = msg.mode === "application_form_wait";

    const body = el("div", {}, [
        el("div", {
            class: "confirm-msg",
            style: "white-space: pre-wrap;",
            text: message,
        }),
        el("div", { class: "login-url-row" }, [
            el("label", { class: "field-label", text: "受管窗口当前目标" }),
            el("div", { class: "login-url-box" }, [
                el("input", {
                    class: "input login-url-input",
                    type: "text",
                    value: loginUrl,
                    readonly: "true",
                }),
            ]),
        ]),
        el("p", {
            style: "margin: 12px 0 0; font-size: 12px; color: var(--gray-500);",
            text: isFormRecovery
                ? (isCurrentPageWait
                    ? "浏览器与任务正在保持运行。这里只检测当前受管窗口，不会返回岗位列表或再次点击申请。"
                    : "浏览器与任务正在保持运行。可先在同一受管窗口中手动调整页面，再回来重新检测。")
                : "只操作此前自动弹出并执行岗位搜索的同一个受管窗口。确认后系统会自动返回所选岗位、点击申请入口并验证表单。",
        }),
    ]);

    const footer = el("div", {}, [
        el("button", {
            class: "btn btn-primary",
            text: isFormRecovery
                ? (isCurrentPageWait
                    ? "检测当前窗口的申请表单"
                    : "重新恢复岗位并检测申请表单")
                : "我已在受管窗口完成登录，继续打开申请表单",
            onclick: () => respond(msg.request_id, "user_login", {
                status: isFormRecovery ? "ready_for_form_check" : "logged_in",
            }),
        }),
    ]);
    openModal(isFormRecovery ? "🧭 等待进入申请表单" : "🔐 需要登录", body, footer);
}

/* ---------------- 健康检查 ---------------- */
async function checkHealth() {
    try {
        const r = await api("/api/health");
        toast(`后端状态：${r.status}`, "success", "健康检查");
    } catch (e) {
        toast(e.message, "error", "后端不可达");
    }
}

/* ---------------- 初始化 ---------------- */
function init() {
    // 导航
    $$(".nav-item").forEach((n) => {
        n.addEventListener("click", (e) => {
            e.preventDefault();
            switchView(n.dataset.view);
        });
    });
    $("#menuToggle").addEventListener("click", () => {
        $("#sidebar").classList.toggle("open");
    });

    // 数据跳转
    document.addEventListener("click", (e) => {
        const t = e.target.closest("[data-jump]");
        if (t) {
            switchView(t.dataset.jump);
        }
    });

    // 投递任务
    $("#addCompanyBtn").addEventListener("click", () => {
        $("#companyList").appendChild(createCompanyRow());
        reindexCompanies();
    });
    $("#startBtn").addEventListener("click", startSession);

    // 文档投递
    $("#startDocBtn").addEventListener("click", startDocumentSession);

    // 文件管理
    setupDropzone();
    $("#refreshFilesBtn").addEventListener("click", loadUploads);
    $("#refreshProfilesBtn").addEventListener("click", loadProfiles);

    // 通知设置
    $("#saveSettingsBtn").addEventListener("click", saveSettings);
    $("#resetSettingsBtn").addEventListener("click", loadSettings);
    // Agent 临时连接
    $("#verifyApiSettingsBtn").addEventListener("click", () => verifyAgentApiSettings());
    $("#clearApiSettingsBtn").addEventListener("click", clearAgentApiSettings);

    // 监控
    $("#clearLogBtn").addEventListener("click", () => {
        $("#logPanel").innerHTML = '<div class="log-empty">日志已清空</div>';
    });
    $("#clearScreenshotsBtn").addEventListener("click", () => {
        $("#screenshotGrid").innerHTML = "";
        $("#screenshotCard").style.display = "none";
    });

    // 对话区域
    $("#chatSendBtn").addEventListener("click", () => {
        sendChatMessage($("#chatInput").value);
    });
    $("#chatInput").addEventListener("keydown", (e) => {
        // 回车发送，Shift+回车换行
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendChatMessage(e.target.value);
        }
    });
    $("#interruptBtn").addEventListener("click", () => {
        const text = prompt("请输入新的指令，Agent 将中断当前流程并按新指令重试：");
        if (text !== null) {
            interruptAgent(text.trim());
        }
    });
    $("#stopSessionBtn").addEventListener("click", stopCurrentSession);

    // 记忆
    $("#refreshMemoryBtn").addEventListener("click", loadMemory);

    // 模态
    $("#modalClose").addEventListener("click", closeModal);
    $("#modalMask").addEventListener("click", (e) => {
        if (e.target.id === "modalMask") closeModal();
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && $("#modalMask").classList.contains("open")) closeModal();
    });

    // 顶栏
    $("#healthBtn").addEventListener("click", checkHealth);

    // 初始数据
    setConnStatus("idle");
    $("#companyList").appendChild(createCompanyRow());

    // 并行加载初始数据
    loadRecruitmentTypes();
    loadUserInfoSummary();
    loadProfiles();
    loadAgentApiSettings();
    // 设置在切到该视图时再加载

    // 旋转动画样式（追加）
    const style = document.createElement("style");
    style.textContent = `.spin { animation: spin 0.9s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }`;
    document.head.appendChild(style);
}

document.addEventListener("DOMContentLoaded", init);

})();
