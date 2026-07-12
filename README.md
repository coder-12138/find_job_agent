# 简历自动投递 Agent (LangChain/LangGraph 版)

基于 **LangChain** 和 **LangGraph** 框架的智能简历投递 Agent，能够根据用户提供的简历和个人信息文档，自动完成校招网申的批量投递工作。本仓库为项目的 LangChain/LangGraph 实现版本。

> 🚧 **Web UI 开发中**：基于 FastAPI + WebSocket 的 Web 管理界面正在开发中，未来将支持通过浏览器可视化管理投递任务。

## 功能特性

- 自动搜索和定位目标公司的招聘官网
- 根据用户条件筛选并推荐岗位
- 自动填写校招简历表单（支持文本框、下拉菜单、单选按钮、日历组件等）
- 支持简历附件上传
- 支持批量投递多家公司（并行或顺序模式）
- **智能记忆功能**：自动记录用户补充的个人信息，避免重复询问
- 支持多种通知方式（终端打印、系统弹窗、邮件通知）

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

## 运行测试

```bash
PYTHONPATH=src python -m pytest tests_langchain/ -v
```

## 项目结构

```
src/job_application_agent_langchain/
├── main.py                # 主入口
├── config.py              # 配置管理
├── context.py             # 数据模型
├── memory.py              # 记忆存储模块
├── utils.py               # 工具函数
├── agents/
│   ├── orchestrator.py    # LangGraph 工作流编排
│   ├── search.py          # Search Agent Node
│   └── form.py            # Form Agent Node
├── browser/
│   └── automation.py      # Playwright 浏览器自动化
├── tools/
│   └── notify.py          # 通知工具
└── user_info/
    └── parser.py          # 用户信息解析
```

## 记忆功能说明

当表单需要填写某个**必填字段**，但在用户的个人信息文档中找不到时：

1. Agent 暂停执行，询问用户该字段的值
2. 用户回答后，自动记录到 `data/memory.json`
3. 下次遇到相同字段时，直接使用记忆中的值，不再询问

## 注意事项

- 首次运行前请确保已配置 `OPENAI_API_KEY`
- 建议先在少量公司上测试，确认流程正确后再批量投递
- 投递前会有确认提示，请仔细检查
- 部分网站可能有反爬虫机制，需要手动干预
