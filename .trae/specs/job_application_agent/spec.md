# 自动校招简历投递Agent - Product Requirement Document

## Overview

- **Summary**: 一个基于 `openai-agents` 包（版本 > 0.14.1）的智能简历投递Agent，能够根据用户提供的简历和个人信息文档，自动完成校招网申的批量投递工作。
- **Purpose**: 解决校招网申过程中重复填写简历、筛选岗位等繁琐工作，提高求职效率。
- **Target Users**: 正在进行校招网申的应届毕业生或求职者。

## Goals

- 自动搜索和定位目标公司的招聘官网
- 根据用户条件筛选最合适的岗位
- 自动填写校招简历表单（支持下拉菜单、单选按钮、日历组件等多种表单元素，能够自动适应不同公司的简历投递系统）
- 支持简历附件上传和简历解析器
- 支持批量投递多家公司
- 提供用户审核和确认机制
- 遇到问题时主动寻求用户帮助
- 使用.env文件配置API信息
- 使用专门的conda环境开发

## Non-Goals (Out of Scope)

- 绕过需要复杂验证码或人脸识别的网站
- 保证100%投递成功（部分网站可能有反爬虫机制）
- 自动完成所有公司的账号注册
- 修改已投递的志愿

## Background & Context
- 使用 `openai-agents` 包（版本 > 0.14.1）作为核心框架，**采用多 agent 架构**
- 需要处理各种不同的招聘网站UI结构
- 需要理解和填写各种表单元素（文本框、下拉框、单选按钮、日历组件等）
- 用户在使用前需要自行在.env中配置所用的模型的API key和url等信息
- **目标运行环境**：
  - **Windows个人电脑**（有桌面环境）：主要运行环境，需要支持系统弹窗通知
  - **Linux服务器**（SSH连接，无桌面环境）：仅终端通知，无需弹窗
  - **macOS**（终端命令行）：支持系统弹窗通知+ 终端通知

### 多 Agent 架构设计
采用 **分层编排 + 并行处理 + 职责细分** 的多 agent 架构：

```
┌─────────────────────────────────────────────────────────────────┐
│              Orchestrator Agent（协调主 Agent）                 │
│  - 接收用户输入，管理全局状态                                    │
│  - 协调各子 Agent 工作                                          │
│  - 处理用户交互（Human-in-the-loop）                             │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  Company X Flow │  │  Company Y Flow │  │  Company Z Flow │
│  (可并行)       │  │  (可并行)       │  │  (可并行)       │
└─────────────────┘  └─────────────────┘  └─────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  Search Agent   │  │  Search Agent   │  │  Search Agent   │
│  - 搜索公司官网 │  │  - 搜索公司官网 │  │  - 搜索公司官网 │
│  - 查找岗位信息 │  │  - 查找岗位信息 │  │  - 查找岗位信息 │
│  - 岗位匹配推荐 │  │  - 岗位匹配推荐 │  │  - 岗位匹配推荐 │
│  - 随时调用通知 │  │  - 随时调用通知 │  │  - 随时调用通知 │
│    Tool          │  │    Tool          │  │    Tool          │
└─────────────────┘  └─────────────────┘  └─────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   Form Agent    │  │   Form Agent    │  │   Form Agent    │
│  - 简历附件上传 │  │  - 简历附件上传 │  │  - 简历附件上传 │
│  - 简历解析处理 │  │  - 简历解析处理 │  │  - 简历解析处理 │
│  - 表单自动填写 │  │  - 表单自动填写 │  │  - 表单自动填写 │
│  (下拉/单选/日 │  │  (下拉/单选/日 │  │  (下拉/单选/日 │
│   历等)         │  │   历等)         │  │   历等)         │
│  - 投递确认与   │  │  - 投递确认与   │  │  - 投递确认与   │
│    执行（可选） │  │    执行（可选） │  │    执行（可选） │
│  - 随时调用通知 │  │  - 随时调用通知 │  │  - 随时调用通知 │
│    Tool          │  │    Tool          │  │    Tool          │
└─────────────────┘  └─────────────────┘  └─────────────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │
                              ▼
                   ┌───────────────────────────┐
                   │  通知 Tool (Notify User)  │
                   │  - 终端打印（全平台）     │
                   │  - 系统弹窗（Windows/macOS）│
                   │  - 邮件通知（可选）        │
                   │  - 支持用户确认输入        │
                   └───────────────────────────┘
```

**架构说明**：
- **Orchestrator Agent**：使用 handoffs 和 agent-as-tool 模式协调子 Agent
- **Search Agent**：每个公司一个独立实例，专门负责搜索官网、查找岗位，可随时调用通知 Tool
- **Form Agent**：每个公司一个独立实例，专注处理各种表单组件，并包含投递确认与执行功能，可随时调用通知 Tool
- **通知 Tool**：所有 Agent 共享的通用 Tool，用于随时通知用户，支持终端打印、系统弹窗、邮件通知，可根据需要等待用户确认

### 工作流程
对于每个公司（可并行处理）：
1. Orchestrator 启动该公司的 Search Agent
2. Search Agent 搜索公司官网，查找并推荐岗位
3. **用户决定投递的岗位并自行注册账号**，进入简历创建页面
4. Orchestrator 启动该公司的 Form Agent
5. Form Agent 完成简历填写后，弹出醒目警告，询问用户是否由 AI 进行投递
6. 若用户选择否，直接结束该公司流程
7. 若用户选择是，Form Agent 执行投递操作

## Functional Requirements

- **FR-1**: 用户可输入公司名称、内推码、岗位关键词、工作城市等参数
- **FR-2**: Agent能自动搜索并定位各公司的招聘官网
- **FR-3**: 根据Job Description匹配并推荐2n个候选岗位（n为该公司可投递最大岗位数）
- **FR-4**: 从招聘官网查询可投递的最大岗位数n
- **FR-5**: 支持用户选择志愿顺序
- **FR-6**: 自动填写校招简历表单（包括文本框、下拉菜单、单选按钮、复选框等）
- **FR-7**: 支持日历组件选择日期，精确到月或日根据网站要求
- **FR-8**: 信息缺失时不填写，避免张冠李戴
- **FR-9**: 支持简历附件上传
- **FR-10**: 支持用户选择是否使用简历解析器进行解析
- **FR-11**: 每完成一家公司的简历填写后暂停，等待用户检查
- **FR-12**: 支持后台并行处理多家公司的简历填写
- **FR-13**: 最终投递前提供醒目的确认提醒
- **FR-14**: 遇到未知问题时主动向用户询问
- **FR-15**: 使用.env文件配置API key、url等信息
- **FR-16**: 使用专门的conda环境开发
- **FR-17**: 支持多种通知方式（终端打印[全平台]、Windows/macOS系统弹窗、邮件通知[可选]）
- **FR-18**: 邮件通知功能可由用户选择是否开启
- **FR-19**: 邮件发送配置在.env中设置（发件邮箱、SMTP服务器等）
- **FR-20**: 提供详细的邮箱设置教程
- **FR-21**: 在Linux服务器（SSH）和无桌面环境下降级为纯终端通知，不报错

## Non-Functional Requirements
- **NFR-1**: 交互响应时间 < 5秒
- **NFR-2**: 支持至少5家主流招聘网站
- **NFR-3**: 用户信息安全存储（不持久化敏感信息）
- **NFR-4**: 平台兼容性：Windows（终端+弹窗）、Linux服务器（SSH终端）、macOS（终端+弹窗）

## Constraints
- **Technical**: 必须使用 `openai-agents` 包（通过 `pip install openai-agents` 安装），**版本 > 0.14.1**，Python语言，使用Playwright浏览器自动化工具；**必须启用沙箱功能**限制 Agent 文件系统访问权限
- **Security**: Agent 只能读取用户指定的简历/个人信息目录，只能写入系统临时目录；禁止修改系统配置和用户主目录下的重要文件
- **Business**: 不保证所有网站兼容，部分网站可能需要手动干预
- **Dependencies**: OpenAI API, Playwright, python-dotenv

## Assumptions

- 用户能提供完整的简历和个人信息文档
- 用户愿意在必要时手动辅助解决问题
- 用户有目标公司的招聘官网账号或愿意自行注册
- 用户会在使用前配置好.env文件中的API信息
- 用户会创建和使用专门的conda环境

## Acceptance Criteria

### AC-1: 输入参数接收

- **Given**: 用户启动Agent
- **When**: 用户输入公司列表、岗位关键词、工作城市等信息
- **Then**: Agent成功接收并存储这些参数
- **Verification**: `programmatic`

### AC-2: 招聘官网搜索

- **Given**: Agent接收到公司名称
- **When**: Agent执行搜索
- **Then**: Agent找到并导航到该公司的招聘官网
- **Verification**: `programmatic`

### AC-3: 岗位推荐

- **Given**: Agent在招聘官网上
- **When**: Agent搜索符合条件的岗位
- **Then**: 
  1. Agent返回2n个最相关的岗位供用户选择
  2. 每个岗位包含：
     - 岗位名称
     - 工作地点
     - 完整 Job Description
     - **推荐理由**（基于用户简历和岗位要求的匹配度分析）
- **Verification**: `programmatic` + `human-judgment`

### AC-4: 简历自动填写 - 多种表单元素

- **Given**: 用户已选择志愿顺序，Agent进入简历填写页面
- **When**: Agent处理表单
- **Then**: Agent正确填写文本框、选择下拉菜单、点击单选按钮、勾选复选框
- **Verification**: `programmatic` + `human-judgment`

### AC-5: 日期填写 - 日历组件支持

- **Given**: Agent遇到日期填写字段
- **When**: Agent处理日期字段
- **Then**: Agent使用日历组件选择正确的日期，精确到月或日根据网站要求
- **Verification**: `programmatic`

### AC-6: 信息缺失处理

- **Given**: 表单需要填写的信息在用户提供的文档中不存在
- **When**: Agent遇到缺失信息的字段
- **Then**: Agent跳过该字段，不填写任何内容，不张冠李戴
- **Verification**: `programmatic`

### AC-7: 简历附件上传
- **Given**: 用户提供了简历附件
- **When**: Agent遇到上传简历的功能
- **Then**: Agent成功上传简历附件
- **Verification**: `programmatic`

### AC-8: 简历解析器选择与处理
- **Given**: 网站提供简历解析功能
- **When**: 用户可以选择是否使用解析器
- **Then**: 
  1. Agent询问用户是否使用简历解析器
  2. **用户选择不使用解析器**：
     - 若网站支持只上传不解析：直接上传，不触发解析
     - 若网站自动解析：忽略解析结果，重新填写所有字段
  3. **用户选择使用解析器**：
     - 使用网站解析器解析简历
     - 对比解析内容与用户信息，识别错误和缺失
     - 自动修正错误，补充缺失内容
- **Verification**: `programmatic` + `human-judgment`

### AC-9: 审核暂停机制

- **Given**: Agent完成一家公司的简历填写
- **When**: Agent准备投递前
- **Then**: Agent暂停，通知用户检查，同时可以处理下一家公司
- **Verification**: `programmatic`

### AC-10: 投递确认与执行（每个公司独立）

- **Given**: Search Agent 已推荐岗位，用户已决定投递的岗位并自行注册账号进入简历创建页面，Form Agent 已完成简历填写
- **When**: Form Agent 准备进行投递
- **Then**: 
  1. Form Agent 弹出醒目警告，询问用户是否由 AI 进行投递：
     > **⚠️ 重要警告**：执行此步，AI agent将直接自动完成简历投递，不会再暂停让您检查并确认，部分校招网站一旦投递后，无法（或者很难）修改志愿和投递岗位，请谨慎选择
  2. 若用户选择否，直接结束该公司流程
  3. 若用户选择是，Form Agent 执行该公司的投递操作
- **Verification**: `programmatic` + `human-judgment`

### AC-11: 问题处理机制

- **Given**: Agent遇到无法解决的问题
- **When**: 问题发生
- **Then**: Agent暂停并询问用户解决方案
- **Verification**: `programmatic`

### AC-12: .env配置支持

- **Given**: 用户在.env中配置了API信息
- **When**: Agent启动
- **Then**: Agent成功读取并使用.env中的配置
- **Verification**: `programmatic`

### AC-13: 多种通知方式支持
- **Given**: Agent需要通知用户（暂停、完成、错误等）
- **When**: Agent触发通知
- **Then**: 
  - Windows/macOS环境：同时使用终端打印和系统弹窗通知用户
  - Linux环境：仅使用终端打印通知用户
  - 可叠加邮件通知（如已开启）
- **Verification**: `programmatic`

### AC-14: Windows/macOS系统弹窗通知
- **Given**: Agent在Windows或macOS环境中触发通知
- **When**: Agent需要提醒用户检查或确认
- **Then**: Windows系统托盘/macOS通知中心弹出通知气泡，用户点击可查看详情
- **Verification**: `programmatic`

### AC-15: 无桌面环境优雅降级
- **Given**: Agent运行在Linux服务器（SSH）环境中
- **When**: Agent尝试调用系统弹窗
- **Then**: Agent自动检测到无桌面环境，仅使用终端打印，不抛出异常
- **Verification**: `programmatic`

### AC-16: 邮件通知功能

- **Given**: 用户在.env中开启了邮件通知并配置了邮箱信息
- **When**: Agent触发通知事件
- **Then**: Agent成功发送邮件到指定收件箱
- **Verification**: `programmatic`

### AC-17: 邮件通知开关控制

- **Given**: 用户在.env中设置邮件通知为开启/关闭
- **When**: Agent启动时读取配置
- **Then**: Agent根据设置决定是否启用邮件通知
- **Verification**: `programmatic`

### AC-18: 邮件配置教程完整性
- **Given**: 用户查看用户手册
- **When**: 用户按照教程配置邮件通知
- **Then**: 用户能成功配置并收到测试邮件
- **Verification**: `human-judgment`

### AC-19: 沙箱安全限制
- **Given**: Agent 正在运行
- **When**: Agent 尝试执行文件操作
- **Then**: 
  - 只能读取用户指定的简历/个人信息目录
  - 只能写入系统临时目录
  - 无法修改系统配置文件或用户主目录下的重要文件
- **Verification**: `programmatic`

## Open Questions

- [ ] 新版OpenAI Agent SDK的具体包名和安装方式？
- [ ] 用户简历和个人信息文档的格式要求？

