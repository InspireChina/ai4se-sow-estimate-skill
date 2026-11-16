# 订单中心 技术方案（高阶设计）

## 1. 总体结构

订单中心采用前后端分离：前端为运营后台 Web 应用，后端提供订单查询与操作 API，
数据存储使用已有的 MySQL 集群，通过消息队列同步订单状态变更到履约系统。

## 2. 领域模型

### 订单 Order

- id: UUID，主键
- 订单号: string，唯一
- 商家编码: string，多租户隔离键
- 状态: enum(待付款, 待发货, 已发货, 已取消)
- 下单时间: datetime
- 总金额: decimal

### 订单行 OrderLine

- 商品编码: string
- 商品名称: string
- 数量: int
- 单价: decimal

### 订单操作日志 OrderOperationLog

- 订单号: string
- 操作类型: enum(发货, 取消)
- 操作人: string
- 备注: string
- 操作时间: datetime

## 3. API 设计

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/orders | 按条件查询订单列表，支持分页与排序 |
| GET | /api/orders/{orderId} | 查询订单详情 |
| POST | /api/orders/{orderId}/ship | 提交发货信息 |
| POST | /api/orders/{orderId}/cancel | 取消订单 |
| GET | /api/orders/export | 导出当前筛选结果 |

## 4. 关键设计取舍

- 列表查询走订单主表索引 + 商家维度分片，导出走异步任务，避免大结果集压库
- 发货与取消通过本地事务写库，再投递订单状态变更消息，保证最终一致
- 状态机集中在订单领域服务内校验，避免各入口重复判断

## 5. 部署与运维

- 新应用独立部署，复用现有 Kubernetes 集群与统一日志、监控接入
- 接口需接入统一网关鉴权
