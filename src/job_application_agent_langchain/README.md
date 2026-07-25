# 简历自动投递Agent (LangChain/LangGraph 重构版)

基于 **LangChain** 和 **LangGraph** 框架的智能简历投递Agent，能够根据用户提供的简历和个人信息文档，自动完成校招网申的批量投递工作。

## 功能特性

- 自动搜索和定位目标公司的招聘官网
- 根据用户条件筛选并推荐岗位
- 自动填写校招简历表单（支持文本框、下拉菜单、单选按钮、日历组件等）
- 支持简历附件上传
- 支持批量投递多家公司（并行或顺序模式）
- **智能记忆功能**：自动记录用户补充的个人信息，避免重复询问
- 支持多种通知方式（终端打印、系统弹窗、邮件通知）

## 环境要求

- Python 3.10+
- Conda（推荐）或 pip

## 安装配置

### 1. 创建 Conda 环境

```bash
conda create -n job_agent_langchain python=3.12
conda activate job_agent_langchain
```

### 2. 安装依赖

```bash
pip install langchain langgraph langchain-openai playwright python-dotenv pydantic plyer pytest
playwright install chromium
```

### 3. 配置 .env 文件

在项目根目录创建 `.env` 文件：

```env
# LLM 配置（必填）
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_API_BASE=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o

# 个人信息文件路径（可选，有默认值）
PERSONAL_INFO_FILE_PATH=data/personal_information.txt
RESUME_FILE_PATH=

# 浏览器配置
BROWSER_HEADLESS=true
BROWSER_TIMEOUT=30000

# 邮件通知（可选）
EMAIL_NOTIFICATION_ENABLED=false
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_SENDER_EMAIL=your-email@gmail.com
SMTP_SENDER_PASSWORD=your-app-password
SMTP_RECIPIENT_EMAIL=recipient@example.com

# 记忆文件路径（可选）
MEMORY_FILE_PATH=data/memory.json
```

### 4. 准备个人信息文件

在 `data/` 目录下准备 `personal_information.txt` 文件，格式参考项目中的示例文件。

## 使用方法

### 运行主程序

```bash
cd /data3/zhuym/find_job_agent
PYTHONPATH=src python -m job_application_agent_langchain.main
```

### 运行测试

```bash
cd /data3/zhuym/find_job_agent
PYTHONPATH=src python -m pytest tests_langchain/ -v
```

## 项目结构

```
job_application_agent_langchain/
├── __init__.py
├── config.py              # 配置管理
├── context.py             # 数据模型
├── memory.py              # 记忆存储模块
├── utils.py               # 工具函数
├── main.py                # 主入口
├── agents/
│   ├── __init__.py
│   ├── orchestrator.py    # LangGraph 工作流编排
│   ├── search.py          # Search Agent Node
│   └── form.py            # Form Agent Node
├── browser/
│   ├── __init__.py
│   └── automation.py      # Playwright 浏览器自动化
├── tools/
│   ├── __init__.py
│   └── notify.py          # 通知工具
└── user_info/
    ├── __init__.py
    └── parser.py          # 用户信息解析
```

## 工作流程

```
用户输入公司列表
       ↓
  Orchestrator Node
       ↓
   Router Node ──→ Search Agent Node（搜索官网、推荐岗位）
       ↓                  ↓
   Human-in-the-loop（用户选择岗位、注册账号）
       ↓
   Router Node ──→ Form Agent Node（填写表单、记忆缺失信息）
       ↓                  ↓
   Human-in-the-loop（投递确认）
       ↓
      END
```

## 记忆功能说明

当表单需要填写某个**必填字段**，但在用户的个人信息文档中找不到时：

1. Agent 暂停执行，询问用户该字段的值
2. 用户回答后，自动记录到 `data/memory.json`
3. 下次遇到相同字段时，直接使用记忆中的值，不再询问

查看已记录的信息：
```bash
cat data/memory.json
```

## 邮件通知配置（可选）

如需启用邮件通知，请在 `.env` 中配置：

1. 设置 `EMAIL_NOTIFICATION_ENABLED=true`
2. 配置 SMTP 服务器信息
3. 对于 Gmail，需要使用[应用专用密码](https://support.google.com/accounts/answer/185833)而非账户密码

## 注意事项

- 首次运行前请确保已配置 `OPENAI_API_KEY`
- 建议先在少量公司上测试，确认流程正确后再批量投递
- 投递前会有确认提示，请仔细检查
- 部分网站可能有反爬虫机制，需要手动干预

## 与原版区别

| 特性 | 原版 (openai-agents) | 重构版 (LangChain/LangGraph) |
|------|---------------------|------------------------------|
| 框架 | openai-agents > 0.14.1 | LangChain + LangGraph |
| 架构 | handoffs + agent-as-tool | StateGraph 图结构 |
| 记忆功能 | 无 | 支持持久化记忆 |
| 并行处理 | 支持 | 支持（子图并行） |
| Human-in-the-loop | 基于工具 | LangGraph interrupt |
