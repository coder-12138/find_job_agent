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

/* 简历字段中文标签（resume_review） */
const RESUME_LABELS = {
    self_introduction: "自我介绍",
    project_highlights: "项目亮点",
    skill_highlights: "技能亮点",
    work_highlights: "工作亮点",
    summary: "总结",
};

/* ---------------- 应用状态 ---------------- */
const state = {
    currentView: "home",
    recruitmentTypes: RECRUITMENT_TYPES,
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
    settings: "通知设置",
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
    if (view === "files") loadUploads();
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
        }))
        .filter((c) => c.company_name);

    if (!companies.length) {
        toast("请至少添加一家公司（公司名称必填）", "warning", "无法开始");
        return;
    }

    const parallel = $("#parallelMode").checked;

    const btn = $("#startBtn");
    btn.disabled = true;
    btn.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="spin"><circle cx="12" cy="12" r="10" stroke-dasharray="40 20"/></svg> 启动中…';

    try {
        const res = await api("/api/sessions", {
            method: "POST",
            json: { companies, parallel },
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
        } catch (e) {
            toast(`${file.name}：${e.message}`, "error", "上传失败");
        }
        done++;
    }
    fill.style.width = "100%";
    text.textContent = `完成 ${done}/${files.length}`;
    setTimeout(() => { progress.style.display = "none"; fill.style.width = "0%"; }, 1200);
    loadUploads();
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
        setConnStatus(state.session.status === "completed" ? "connected" : "error");
        if (state.session.status !== "completed" && state.session.status !== "error") {
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
        if (state.session.status === "completed" || state.session.status === "error") return;
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
        case "error":
            addLog("error", msg.message || "未知错误");
            toast(msg.message || "错误", "error", "Agent 错误");
            break;
        default:
            console.debug("未处理的消息类型", msg);
    }
}

function handleProgress(msg) {
    const phase = msg.phase;
    const company = msg.company || "";
    const message = msg.message || "";

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
        if (r.error_message) state.session.companies[company].error = r.error_message;
    }
    addLog("success", `[${company}] 投递结果：${JSON.stringify(msg.result || {})}`);
    renderCompanyCards();
}

function handleSessionComplete(msg) {
    state.session.status = "completed";
    state.session.results = msg.results || {};
    updateSessionStatus("completed");
    addLog("success", "会话已完成");
    toast("投递会话已完成", "success", "完成");

    const card = $("#resultCard");
    card.style.display = "block";
    $("#resultPre").textContent = JSON.stringify(msg.results, null, 2);
    renderCompanyCards();
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
    };
    const m = map[status] || map.pending;
    $("#sessionStatus").innerHTML = `<span class="status-badge ${m.cls}">${m.text}</span>`;
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
    const editable = {}; // 可编辑副本

    const body = el("div", {}, [
        el("p", {
            style: "margin: 0 0 12px; font-size: 13px; color: var(--gray-600);",
            text: "对比原始与润色后的简历内容。可在右侧编辑后提交，或直接采用润色版本。",
        }),
    ]);

    const compare = el("div", { class: "resume-compare" });

    // 原始列
    const origCol = el("div", { class: "resume-col" }, [el("h4", { text: "原始内容" })]);
    // 润色列
    const polCol = el("div", { class: "resume-col polished" }, [el("h4", { text: "润色内容（可编辑）" })]);

    Object.keys(RESUME_LABELS).forEach((key) => {
        const origVal = original[key];
        const polVal = polished[key];

        // 原始
        origCol.appendChild(
            el("div", { class: "resume-section" }, [
                el("div", { class: "resume-section-label", text: RESUME_LABELS[key] }),
                el("div", {
                    class: "resume-section-value",
                    text: formatResumeValue(origVal) || "—",
                }),
            ])
        );

        // 润色（可编辑）
        const textVal = formatResumeValue(polVal);
        editable[key] = textVal;
        const textarea = el("textarea", {
            rows: key === "self_introduction" || key === "summary" ? 4 : 5,
        });
        textarea.value = textVal;
        textarea.addEventListener("input", () => { editable[key] = textarea.value; });

        polCol.appendChild(
            el("div", { class: "resume-section" }, [
                el("div", { class: "resume-section-label", text: RESUME_LABELS[key] }),
                textarea,
            ])
        );
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
                // 将可编辑文本解析回结构
                const confirmed = {};
                Object.keys(editable).forEach((k) => {
                    const originalPolVal = polished[k];
                    if (Array.isArray(originalPolVal)) {
                        // 尝试按行解析为数组（每行一项 JSON 或纯文本）
                        const lines = editable[k].split("\n").map((s) => s.trim()).filter(Boolean);
                        confirmed[k] = lines.map((line) => {
                            try { return JSON.parse(line); }
                            catch { return { value: line }; }
                        });
                    } else {
                        confirmed[k] = editable[k];
                    }
                });
                respond(msg.request_id, "resume_review", { confirmed });
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

    // 文件管理
    setupDropzone();
    $("#refreshFilesBtn").addEventListener("click", loadUploads);

    // 通知设置
    $("#saveSettingsBtn").addEventListener("click", saveSettings);
    $("#resetSettingsBtn").addEventListener("click", loadSettings);

    // 监控
    $("#clearLogBtn").addEventListener("click", () => {
        $("#logPanel").innerHTML = '<div class="log-empty">日志已清空</div>';
    });
    $("#clearScreenshotsBtn").addEventListener("click", () => {
        $("#screenshotGrid").innerHTML = "";
        $("#screenshotCard").style.display = "none";
    });

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
    // 设置在切到该视图时再加载

    // 旋转动画样式（追加）
    const style = document.createElement("style");
    style.textContent = `.spin { animation: spin 0.9s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }`;
    document.head.appendChild(style);
}

document.addEventListener("DOMContentLoaded", init);

})();
