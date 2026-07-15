# 简历自动投递 Agent (LangChain/LangGraph 版)

基于 **LangChain** 和 **LangGraph** 框架的智能简历投递 Agent，能够根据用户提供的简历和个人信息文档，自动完成校招网申的批量投递工作。本仓库为项目的 LangChain/LangGraph 实现版本。

## 功能特性

- 自动搜索和定位目标公司的招聘官网
- 根据用户条件筛选并推荐岗位
- 自动填写校招简历表单（支持文本框、下拉菜单、单选按钮、日历组件等）
- 支持简历附件上传
- 支持批量投递多家公司（并行或顺序模式）
- **智能记忆功能**：自动记录用户补充的个人信息，避免重复询问
- 支持多种通知方式（终端打印、系统弹窗、邮件通知）
- 基于 **deep agents** 框架的公司子 Agent 架构（一家公司一个子 Agent）
- 基于岗位 JD 的简历自适应润色，突出匹配内容提升竞争力
- 提供 **Web UI** 管理界面，支持浏览器可视化管理投递任务与实时监控

## 环境要求

- Python 3.12+
- Conda（推荐）或 pip

## 安装

### 1. 创建 Conda 环境

```bash
conda create -n job_agent_langchain python=3.12
conda activate job_agent_langchain
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

依赖包括 `langchain`、`langgraph`、`langchain-openai`、`deepagents`、`playwright`、`python-dotenv`、`plyer`、`pydantic`、`fastapi`、`uvicorn`、`websockets`、`python-multipart` 等组件。

### 3. 配置 .env 文件

```bash
cp .env.example .env
```

编辑 `.env`，填写 `OPENAI_API_KEY`、`OPENAI_API_BASE`、`OPENAI_MODEL` 等配置项，可按需开启邮件通知与浏览器配置。

### 4. 准备个人信息文件

在 `data/` 目录下准备 `personal_information.txt` 文件，格式参考项目示例文件。

## 运行

```bash
PYTHONPATH=src python -m job_application_agent_langchain.main
```

## Web UI 使用

除命令行模式外，本项目提供基于 FastAPI + WebSocket 的 Web 管理界面，可通过浏览器可视化管理投递任务。

### 启动 Web UI

```bash
# 方式一：通过启动脚本（会先校验 .env 配置）
PYTHONPATH=src python -m job_application_agent_langchain.web.run

# 方式二：直接使用 uvicorn
uvicorn job_application_agent_langchain.web.app:app --host 0.0.0.0 --port 8000
```

启动后，在浏览器打开 [http://localhost:8000](http://localhost:8000) 即可进入 Web UI。API 文档位于 [http://localhost:8000/docs](http://localhost:8000/docs)。

### 使用流程

配置公司投递任务 → 上传简历/学历证明/成绩单 → 配置邮件通知 → 启动投递 → 实时监控进度 → 人机交互（选岗/简历润色审核/补充缺失字段/投递确认） → 查看记忆

### 人机交互

投递过程中，Agent 会在关键节点通过 Web UI 弹出交互面板等待用户决策，共支持 4 种交互类型：

1. **岗位选择**：从搜索到的推荐岗位中选择要投递的岗位（含志愿顺序）
2. **简历润色审核**：展示润色前后对比（原版 vs 润色版），用户可编辑修改润色内容后确认
3. **缺失字段批量补充**：表单填写完成后一次性展示所有缺失的必填项，用户批量补充
4. **投递确认**：投递前弹出醒目警告，由用户决定是否由 AI 自动完成投递

### 记忆复用

用户补充的缺失字段会保存到记忆文件（`data/memory.json`），下次投递遇到相同字段时自动复用，无需重复询问。

### 基于 JD 的简历自适应润色

用户选定目标岗位后，系统获取该岗位的完整 JD（职位描述），使用 LLM 分析 JD 要求与用户简历内容的匹配度，生成针对性简历版本（突出匹配的项目经历、技能与关键词），经用户在 Web UI 审核编辑后填入表单。

## 运行测试

```bash
PYTHONPATH=src python -m pytest tests_langchain/ -v
```

## 项目结构

```
src/job_application_agent_langchain/
├── main.py                # 主入口（命令行模式）
├── config.py              # 配置管理
├── context.py             # 数据模型
├── memory.py              # 记忆存储模块
├── utils.py               # 工具函数
├── agent_events.py        # Agent 事件抽象与 CLI 实现
├── agents/
│   ├── orchestrator.py    # 投递流程编排器（并行/顺序）
│   ├── company_agent.py   # 公司子 Agent（deepagents harness）
│   ├── search.py          # 搜索官网与岗位工具
│   └── form.py            # 表单填写与投递工具
├── browser/
│   └── automation.py      # Playwright 浏览器自动化
├── resume_polish/
│   ├── polisher.py        # 简历润色主模块
│   ├── jd_analyzer.py     # JD 关键要求分析
│   ├── resume_matcher.py  # 简历内容匹配与提取
│   └── prompts.py         # 润色相关 Prompt
├── tools/
│   └── notify.py          # 通知工具
├── user_info/
│   └── parser.py          # 用户信息解析
└── web/
    ├── app.py             # FastAPI 应用主入口
    ├── routes.py          # REST API 路由
    ├── session_manager.py # 会话生命周期管理
    ├── emitter.py         # WebEventEmitter 事件桥接
    ├── schemas.py         # Pydantic 数据模型
    ├── file_storage.py    # 文件上传存储
    ├── settings_store.py  # 通知设置持久化
    ├── run.py             # Web 服务启动脚本
    └── static/            # 前端单页应用（HTML/CSS/JS）
```

## 记忆功能说明

当表单需要填写某个**必填字段**，但在用户的个人信息文档中找不到时：

1. Agent 跳过该字段继续填写其他可填字段，同时将缺失的必填项加入待询问列表
2. 表单填写完成后，批量询问用户所有缺失的必填字段
3. 用户补充后，自动记录到 `data/memory.json`
4. 下次遇到相同字段时，直接使用记忆中的值，不再询问

## 注意事项

- 首次运行前请确保已配置 `OPENAI_API_KEY`
- 建议先在少量公司上测试，确认流程正确后再批量投递
- 投递前会有确认提示，请仔细检查
- 部分网站可能有反爬虫机制，需要手动干预
