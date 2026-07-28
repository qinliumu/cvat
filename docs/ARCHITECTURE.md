# 架构说明

> CVAT 原始架构概览(基线 v2.71.0)+ 魔改切入点规划。CVAT 官方详细文档见 upstream `README.md` 与 `site/`。

## CVAT 架构概览

### 组件栈(`docker-compose.yml`)

| 组件 | 角色 |
|---|---|
| `cvat_server` | 主服务:Django + REST API,supervisord 管理 |
| `cvat_ui` | 前端 SPA(React + TypeScript) |
| `cvat_db` | PostgreSQL 主数据库 |
| `cvat_redis_inmem` | 内存缓存 / 任务队列 |
| `cvat_redis_ondisk` | 磁盘持久化缓存 |
| `cvat_worker_import` / `cvat_worker_export` | 异步导入 / 导出 |
| `cvat_worker_annotation` | 异步标注处理 |
| `cvat_worker_webhooks` | Webhook 分发 |
| `cvat_worker_quality_reports` | 标注质量报告 |
| `cvat_worker_chunks` | 视频/大文件分块 |
| `cvat_worker_consensus` | 共识投票 |
| `cvat_opa` | Open Policy Agent,权限策略 |
| `cvat_clickhouse` | 事件 / 分析数据库 |
| `cvat_vector` + `cvat_grafana` | 日志收集 + 监控面板 |
| `traefik` | 反向代理 + HTTPS |

### 代码组织(顶层目录)

| 目录 | 内容 |
|---|---|
| `cvat/` | Django 后端主应用(settings / apps / models / API) |
| `cvat-ui/` | React 前端 |
| `cvat-core/` | 前端核心库(数据模型 / API 客户端) |
| `cvat-canvas` / `cvat-canvas3d` | 标注画布 |
| `cvat-cli/` | Python 命令行 |
| `cvat-sdk/` | 自动生成的 SDK |
| `cvat-data/` | 数据层 |
| `serverless/` | Serverless 函数(模型推理部署) |
| `ai-models/` | AI 模型封装 |
| `components/` | 部署组件(如 serverless 编排) |
| `supervisord/` | 进程管理配置(nginx / server / worker-pool) |
| `helm-chart/` | Kubernetes 部署 |
| `site/` | Hugo 文档站(子模块,非本项目关注) |
| `tests/` | 测试 |
| `utils/` | 工具脚本 |

### 数据流

```
浏览器 ──HTTP──▶ traefik ──▶ cvat_server (Django REST)
                                  │
                  ┌───────────────┼───────────────┐
                  ▼               ▼               ▼
             cvat_db        cvat_redis      cvat_worker_*
           (元数据)        (缓存/队列)      (异步 import/export/annotation)
                                                      │
                                                      ▼
                                                cvat_data 卷
                                            (原图 + 标注落盘)
```

## 魔改切入点(规划,待 ADR 细化)

按**侵入度从低到高**排序,优先选低侵入:

| 层级 | 切入点 | 侵入度 | 升级风险 | 典型用途 |
|---|---|---|---|---|
| 1 | **部署配置层** | 极低 | 极低 | docker-compose 覆盖、环境变量、Traefik 路由、监控开关 |
| 2 | **Serverless 模型层** | 低 | 低 | `components/serverless/` 加自定义模型函数(YOLO/SAM 适配) |
| 3 | **后端扩展点** | 中 | 中 | Django apps、signals、middleware、REST 路由扩展 |
| 4 | **前端定制** | 中 | 中 | cvat-ui 主题、插件、UI 文案、自定义组件 |
| 5 | **核心数据模型** | 高 | 高 | 改 `cvat/` 的 model —— 会断 SDK/CLI/UI 兼容,慎用 |

**原则**:能用扩展点就不改核心。每处核心魔改(层级 3+)必须有 ADR,说明 why 与升级影响。

## 部署形态

CVAT 标准部署:Docker Compose 一键起全栈,浏览器访问 `http://<server>:8080`。

```bash
docker compose up -d
docker exec -it cvat_server bash -ic 'python3 ~/manage.py createsuperuser'
# 打开 http://<server>:8080
```

AI 辅助标注(serverless 组件):

```bash
docker compose -f docker-compose.yml -f components/serverless/docker-compose.serverless.yml up -d
```

> 部署到生产服务器时:调整 `CVAT_HOST`、挂载 `cvat_data` 卷到大磁盘、配 Traefik HTTPS、按资源精简非核心组件(grafana/vector/clickhouse 可关)。
