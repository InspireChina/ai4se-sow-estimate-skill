# 咨询师预约平台 · 技术方案（高阶设计）

## 1. 概述

本文给出咨询师预约平台的高阶设计：领域模型、接口清单、前端页面结构、数据一致性与部署方案。
三端（管理端、咨询师端、终端用户端）共用同一个后端服务与同一套账号体系，通过角色路由区分入口。

设计约束：

- 订单与支付是核心链路，状态流转集中在订单领域服务内，其它模块只读订单状态。
- 档期（可预约时段）与订单强一致，取消与下单都要占用/释放同一份时段记录。
- 通知、结算与提醒走异步消息，主链路不等待副作用完成。
- 咨询师端与管理端的写操作全部留痕，满足审计要求。

## 2. 总体架构

- 前端：单页应用，按角色划分路由前缀 `/user`、`/consultant`、`/admin`，共享组件库与登录态。
- 后端：单服务分层（接入层 → 应用服务 → 领域服务 → 仓储），数据库为关系型数据库。
- 异步：消息队列承载通知、提醒与结算批处理，消费者幂等。
- 外部依赖：统一支付网关、统一身份认证、短信网关、对象存储（资质与头像文件）。

## 3. 领域模型

### 3.1 实体与字段

#### 用户 User

- 用户ID userId
- 手机号 mobile
- 昵称 nickname
- 头像 avatarUrl
- 邮箱 email
- 所在城市 city
- 账号类型 roleType（终端用户 / 咨询师 / 管理员）
- 账号状态 status（正常 / 禁用 / 已注销）
- 注册时间 createdAt

#### 咨询师 Consultant

- 咨询师ID consultantId
- 关联用户ID userId
- 职称 title
- 执业年限 workYears
- 擅长领域 domain
- 审核状态 auditStatus（待审核 / 已通过 / 已驳回）
- 审核备注 auditRemark
- 综合评分 rating
- 累计咨询量 orderCount
- 综合排序分 score

#### 咨询师档案 ConsultantProfile

- 档案ID profileId
- 咨询师ID consultantId
- 个人简介 introduction
- 服务介绍 serviceIntro
- 咨询方式 serviceMode
- 适用人群 audience
- 头像文件 avatarFileId
- 资质文件 credentialFileId
- 审核版本 version

#### 咨询分类 Category

- 分类ID categoryId
- 上级分类ID parentId
- 分类名称 name
- 排序 sortOrder
- 启用状态 enabled
- 咨询师数量 consultantCount

#### 擅长标签 Tag

- 标签ID tagId
- 标签名称 name
- 使用次数 usageCount

#### 入驻申请 Application

- 申请ID applicationId
- 申请人ID userId
- 姓名 realName
- 执业身份 identity
- 擅长领域 domain
- 从业年限 workYears
- 期望定价 expectedPrice
- 资质文件ID credentialFileId
- 申请状态 status（待审核 / 已通过 / 已驳回）
- 驳回原因 rejectReason
- 审核人ID auditorId
- 审核时间 auditedAt

#### 可预约时段 Availability

- 时段ID slotId
- 咨询师ID consultantId
- 开始时间 startAt
- 结束时间 endAt
- 容量 capacity
- 时段状态 status（空闲 / 已占用 / 已停用）
- 订单ID orderId
- 来源 source（模板生成 / 手工添加）

#### 预约订单 Order

- 订单ID orderId
- 订单号 orderNo
- 用户ID userId
- 咨询师ID consultantId
- 时段ID slotId
- 咨询分类ID categoryId
- 咨询主题 subject
- 问题描述 description
- 咨询单价 unitPrice
- 优惠金额 discountAmount
- 服务费金额 serviceFee
- 实付金额 paidAmount
- 订单状态 status（待支付 / 待确认 / 已确认 / 进行中 / 已完成 / 已取消 / 已退款）
- 支付流水号 paymentNo
- 取消原因 cancelReason
- 评价ID reviewId
- 创建时间 createdAt

#### 咨询记录 Session

- 记录ID sessionId
- 订单ID orderId
- 咨询师ID consultantId
- 用户ID userId
- 开始时间 startedAt
- 结束时间 endedAt
- 咨询小结 summary
- 状态 status（进行中 / 已完成）

#### 评价 Review

- 评价ID reviewId
- 订单ID orderId
- 用户ID userId
- 咨询师ID consultantId
- 总评分 score
- 专业度评分 professionalism
- 响应速度评分 responsiveness
- 沟通体验评分 communication
- 评价内容 content
- 审核状态 auditStatus

#### 结算单 Settlement

- 结算单ID settlementId
- 咨询师ID consultantId
- 结算周期 period
- 订单笔数 orderCount
- 订单金额 orderAmount
- 服务费金额 serviceFee
- 应结金额 payableAmount
- 结算状态 status（待结算 / 已结算 / 提现中 / 已到账）
- 生成时间 generatedAt

#### 举报 Report

- 举报ID reportId
- 举报人ID reporterId
- 被举报对象ID targetId
- 举报类型 type
- 举报说明 description
- 证据附件ID attachmentId
- 处理状态 status（待处理 / 已处理 / 已驳回）
- 处理结果 resolution
- 处理人ID handlerId

#### 操作日志 AuditLog

- 日志ID logId
- 操作人ID operatorId
- 操作类型 action
- 业务对象ID objectId
- 操作结果 result
- 发生时间 occurredAt

### 3.2 状态流转

- 订单：待支付 → 待确认 → 已确认 → 进行中 → 已完成；待支付/待确认可转已取消；已确认可转已退款。
- 入驻申请：待审核 → 已通过 / 已驳回；已驳回可修改后重新提交为新的待审核申请。
- 时段：空闲 → 已占用（下单时抢占）→ 空闲（取消或支付超时后释放）；已占用记录不可物理删除。
- 结算单：待结算 → 已结算 → 提现中 → 已到账。

## 4. 接口设计

### 4.1 终端用户端接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/auth/register | 手机号验证码注册终端用户 |
| POST | /api/auth/login | 手机号验证码登录 |
| GET | /api/users/me | 获取当前用户信息 |
| PUT | /api/users/me | 更新个人资料 |
| GET | /api/users/me/favorites | 查询我的咨询师收藏 |
| DELETE | /api/users/me/favorites/{consultantId} | 取消收藏咨询师 |
| GET | /api/categories | 查询咨询分类与擅长标签 |
| GET | /api/consultants | 检索咨询师，支持关键词、分类、价格区间、评分与时段筛选与排序 |
| GET | /api/consultants/{consultantId} | 查询咨询师主页档案、评分与评价 |
| GET | /api/consultants/{consultantId}/availability | 查询咨询师可预约时段 |
| POST | /api/orders | 创建预约订单并抢占时段 |
| GET | /api/orders | 查询我的预约订单，支持状态筛选与分页 |
| GET | /api/orders/{orderId} | 查询预约订单详情与状态时间线 |
| POST | /api/orders/{orderId}/cancel | 取消订单并释放时段 |
| POST | /api/orders/{orderId}/pay | 发起支付 |
| POST | /api/orders/{orderId}/reviews | 提交订单评价 |
| POST | /api/orders/{orderId}/complaints | 发起订单投诉 |

### 4.2 咨询师端接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/consultant/applications | 提交入驻申请与资质文件 |
| GET | /api/consultant/applications | 查询我的入驻申请与审核进度 |
| GET | /api/consultant/dashboard | 查询咨询师工作台概览指标与待办 |
| GET | /api/consultant/profile | 查询对外展示的档案 |
| PUT | /api/consultant/profile | 更新档案，关键字段变更触发重新审核 |
| GET | /api/consultant/availability | 查询档期模板与例外日期 |
| PUT | /api/consultant/availability | 保存每周档期模板与例外日期 |
| GET | /api/consultant/orders | 查询收到的订单，支持状态筛选 |
| POST | /api/consultant/orders/{orderId}/confirm | 确认订单 |
| POST | /api/consultant/orders/{orderId}/reject | 拒绝订单并填写原因 |
| POST | /api/consultant/orders/{orderId}/start | 开始咨询并创建咨询记录 |
| POST | /api/consultant/orders/{orderId}/complete | 完成咨询并提交咨询小结 |
| POST | /api/consultant/orders/{orderId}/reschedule | 申请改期 |
| GET | /api/consultant/settlements | 查询收入概览与结算单 |
| POST | /api/consultant/settlements/withdrawals | 发起提现申请 |

### 4.3 管理端接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/admin/dashboard | 查询运营看板指标与趋势 |
| GET | /api/admin/applications | 查询入驻申请列表 |
| GET | /api/admin/applications/{applicationId} | 查询申请详情与资质预览 |
| POST | /api/admin/applications/{applicationId}/approve | 审核通过入驻申请 |
| POST | /api/admin/applications/{applicationId}/reject | 驳回入驻申请并记录原因 |
| GET | /api/admin/categories | 查询分类与标签树 |
| POST | /api/admin/categories | 新增分类或标签 |
| PUT | /api/admin/categories/{categoryId} | 编辑、启用或停用分类 |
| GET | /api/admin/users | 检索用户列表 |
| POST | /api/admin/users/{userId}/disable | 禁用违规用户 |
| GET | /api/admin/orders | 检索订单并查看全链路详情 |
| POST | /api/admin/orders/{orderId}/refund | 发起订单退款并通知双方 |
| GET | /api/admin/reports | 查询举报列表 |
| POST | /api/admin/reports/{reportId}/handle | 处理举报并回写处理结果 |
| GET | /api/admin/audit-logs | 查询审计日志 |

### 4.4 外部集成接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/integrations/payments | 支付网关回调，幂等入账 |
| POST | /api/integrations/payments/refunds | 退款结果回调 |
| POST | /api/integrations/identity/sso | 统一身份认证单点登录回调 |

## 5. 前端方案

### 5.1 终端用户端页面

| 路由 | 页面 | 主要元素 |
| --- | --- | --- |
| /user | 首页 | 搜索框、分类筛选、推荐咨询师卡片 |
| /user/search | 检索结果 | 筛选表单、排序、结果列表、分页 |
| /user/consultants/:id | 咨询师主页 | 档案区、评价列表、可预约时段、预约入口 |
| /user/booking/:consultantId | 预约下单 | 订单表单、费用明细、支付方式 |
| /user/orders | 我的预约 | 状态筛选、订单列表、预约提醒 |
| /user/orders/:id | 订单详情 | 状态时间线、费用明细、取消与评价 |
| /user/profile | 个人中心 | 资料表单、收藏列表、协议查看 |

### 5.2 咨询师端页面

| 路由 | 页面 | 主要元素 |
| --- | --- | --- |
| /consultant | 工作台 | 概览指标卡片、待处理订单、公告 |
| /consultant/application | 入驻申请 | 申请表单、资质上传、进度展示 |
| /consultant/profile | 档案维护 | 档案表单、标签选择、头像与资质上传 |
| /consultant/schedule | 档期管理 | 周历、例外日期、批量设置 |
| /consultant/orders | 预约管理 | 状态筛选、订单列表、履约操作 |
| /consultant/settlements | 收入结算 | 收入概览、结算单列表、提现申请 |

### 5.3 管理端页面

| 路由 | 页面 | 主要元素 |
| --- | --- | --- |
| /admin | 运营看板 | 指标卡片、趋势图、分类分布、排行榜 |
| /admin/applications | 入驻审核 | 申请列表、审核详情、资质预览 |
| /admin/categories | 分类标签 | 分类树、表单、启停操作 |
| /admin/users | 用户管理 | 用户检索、用户详情、禁用操作 |
| /admin/orders | 订单监控 | 订单检索、订单详情、退款操作 |
| /admin/reports | 举报处理 | 举报列表、举报详情、处理操作 |

## 6. 数据与一致性

- 订单创建与时段抢占在同一事务内完成，时段抢占使用乐观锁更新，冲突时返回可重试错误。
- 支付与退款以网关回调为准，回调按网关流水号幂等，重复回调不重复入账。
- 消息投递采用本地事务表，消费端按业务键幂等处理。
- 结算单由定时任务按周期生成，任务在多实例下通过分布式锁保证只执行一次。

## 7. 安全与权限

- 接入层统一鉴权，按账号类型与资源归属校验访问权限，禁止越权访问他人订单与档期。
- 咨询师端与管理端接口额外做操作级权限校验，管理端敏感操作需二次确认。
- 手机号、身份证号等字段加密存储，日志与导出做脱敏。
- 文件上传走对象存储，访问使用短期签名地址，资质文件仅审核人与本人可访问。

## 8. 部署与运维

- 前端静态产物与后端服务独立部署，后端多实例并行，数据库主从。
- 环境分为开发、测试、预发、生产四套，生产发布走灰度与回滚流程。
- 定时任务与消息消费者单独部署为后台进程，与 Web 实例解耦。
- 数据库变更走版本化脚本，发布前在预发环境演练并保留回滚脚本。

## 9. 监控与告警

- 应用日志统一采集，接入链路追踪，关键链路 traceId 贯穿网关与下游。
- 核心指标看板含下单成功率、支付回调成功率、时段冲突次数、消息堆积量。
- 告警规则覆盖错误率突增、支付回调失败、消息积压与结算任务未执行。

## 10. 工作量参考

| 模块 | 说明 |
| --- | --- |
| 终端用户端 | 检索、主页、下单支付、订单、评价、个人中心 |
| 咨询师端 | 入驻、档案、档期、履约、结算、工作台 |
| 管理端 | 看板、审核、分类治理、用户与订单治理、举报处理 |
| 平台能力 | 账号与权限、通知、支付集成、审计、配置开关 |
| 工程化 | 初始化、流水线、环境接入、日志监控 |
