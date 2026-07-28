# 项目状态

> 最近更新:2026-07-27

## 当前任务

阶段 1(ODGT format)核心完成:代码已写+注册+push。端到端导出验证待补(需带标注 task,卡在 CVAT v2.71 TUS 上传机制)。下一步:探索 TUS 上传 或 用 ORM 造 task 验证 export,然后进阶段 2。

## 已完成

- [x] CVAT 部署到 hermes(18 容器,admin/admin,SSH 隧道)
- [x] 阶段 0:GitHub fork(qinliumu/cvat)+ xcvat/main 分支 + SSH key + 首批 commit
- [x] 阶段 1 核心代码:`formats/odgt.py`(export+import,187 行)+ registry.py 注册
- [x] 容器内验证:EXPORT_FORMATS/IMPORT_FORMATS 含 ODGT,CVAT 前端下拉会出现 ODGT
- [x] commit `5a37dd374` push 到 fork

## 阶段 1 待补

- [ ] 端到端导出验证:创建带标注 task → 导出 ODGT → 检查 JSON-lines 正确性
  - 卡点:CVAT v2.71 用 TUS 协议上传图片(非简单 multipart),需探索 TUS 或用 ORM 造 task
- [ ] 端到端导入验证:ODGT zip → 导入 CVAT → 看图片+框

## 下一步

- [ ] 解 TUS 上传 或 ORM 造 task,完成阶段 1 端到端验证
- [ ] 阶段 2:nori→CVAT 导入脚本(宿主机 det 环境)
- [ ] 阶段 3:CVAT→nori/ODGT 导出脚本
- [ ] 阶段 4:UI 按钮 + sidecar

## 持久化注意

- 容器内代码是 docker cp 进去的(临时),重建容器会丢。**需做 volume 挂载源码**(改 compose 把宿主机 `/data/xcvat/cvat/cvat/` 挂到容器 `/home/django/cvat/`),作为持久开发环境。这是阶段 1 收尾必做项。

## 已完成

- [x] clone cvat-ai/cvat 完整性校验
- [x] 建立记忆设施:CLAUDE.md + docs/
- [x] 实测 codex/hermes workspace 环境(ADR-004)
- [x] 新建 hermes workspace,建实验目录 `/data/xcvat/`
- [x] rsync 复制 conda det 环境(29G)+ 修复路径软链
- [x] 验证 nori2/refile/brainpp.oss/meghair import OK
- [x] 推 CVAT 源码到 hermes `/data/xcvat/cvat/`(410M,含 .git)
- [x] 装 docker + 解决 iptables-legacy 坑,data-root 迁 /data
- [x] 搭建 xray 代理(systemd 服务,docker 域名走 vless 翻墙),docker daemon 配 HTTP_PROXY
- [x] 拉 CVAT 全部 10 个镜像(v2.71.0),`docker compose up -d` 起 18 容器全 Up
- [x] 创建管理员 admin/admin(superuser)
- [x] 排查办公网无法访问:`100.123.228.217:8080` 内网 IP 办公网够不着,Brain++ 只通过 kubebrain 网关暴露预配置服务(jupyter),自定义端口无外部入口
- [x] 采用方案 A:CVAT_HOST 改 localhost,SSH 端口转发供调试

## 访问方式(调试期,方案 A)

```bash
# 本地电脑终端跑(保持不关):
ssh -L 8080:localhost:8080 qinsenlinhermes.g-qinsenlin.megvii-jg.ws@hh-d.brainpp.cn
# 然后浏览器:http://localhost:8080  (admin/admin)
```
- CVAT_HOST=localhost(traefik 路由匹配 localhost)
- 单人调试用;多人需走方案 C(找 Brain++ 管理员配 kubebrain 网关入口或开放防火墙)

## 下一步

- [ ] 用户浏览器验证 http://localhost:8080 能登录
- [ ] nori → CVAT 数据导入桥(ADR 待立)
- [ ] 在 GitHub fork cvat-ai/cvat,调整 remote(ADR-003 执行)
- [ ] 建立长期魔改集成分支
- [ ] 明确项目正式代号与具体定制场景

## 环境关键事实(hermes)

- **网络**:IP `100.123.228.217`,Brain++ 内网;**办公网无法直连该 IP:8080**(只同集群如 codex 可达)。对外只能通过 Brain++ 网关(kubebrain.io)暴露预配置服务(jupyter base_url=`/kapi/workspace.kubebrain.io/megvii-jg/ws-4601ffe6c8a5ce6a/jupyter`),自定义端口无现成外部入口
- **OS**:Ubuntu 22.04 LTS x86_64,systemd PID1,sudo 免密 + 完整 caps
- **磁盘**:/data 1.0T,docker 数据在 `/data/docker-data`
- **conda det**:已就绪,nori 桥接依赖 import OK
- **CVAT 源码**:`/data/xcvat/cvat/`(410M,含 .git,HEAD=170ce0ad7,基线 v2.71.0)
- **docker**:29.1.3 + compose 2.40.3,iptables-legacy,data-root=/data/docker-data
- **xray 代理**:systemd `xray-proxy.service`,1080/1081,docker 域名走 vless 翻墙
- **CVAT 部署**:`.env` CVAT_VERSION=v2.71.0 + CVAT_HOST=localhost,18 容器全 Up,localhost:8080 可访问(admin/admin)

## 上次会话摘要

**2026-07-27~28**:完成 CVAT 在 hermes 上的部署。路径:校验 clone → 建记忆设施 → 实测环境 → 方案 B workspace+docker(ADR-004)→ rsync conda 环境+软链修复 → 推 CVAT 源码 → 装 docker(iptables-legacy 坑)→ 搭 xray 代理(从 codex 搬,加 docker 域名到 vless 翻墙,systemd 服务)→ 拉 10 镜像 → compose up 18 容器 → 建 admin/admin。**访问问题**:办公网够不着 hermes 内网 IP(只同集群可达),Brain++ 网关只暴露预配置服务。采用方案 A:CVAT_HOST=localhost + SSH 端口转发,localhost:8080 验证 200。
