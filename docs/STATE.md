# 项目状态

> 最近更新:2026-07-27

## 当前任务

在 hermes workspace 上部署 CVAT;conda det 环境已就绪,下一步装 docker。

## 已完成

- [x] clone cvat-ai/cvat 完整性校验:主仓库完整,非浅克隆,114,652 objects,.git 367M
- [x] 确认分支同步:develop@170ce0ad7,与 origin/develop 零 ahead/behind
- [x] 确认子模块 `site/themes/docsy` 未初始化(文档站主题,跑 CVAT 不需要)
- [x] 确认无 LFS 跟踪文件(无漏拉风险)
- [x] 确认 fork 基线:tag v2.71.0
- [x] 建立记忆设施:`CLAUDE.md` / `docs/STATE.md` / `docs/DECISIONS.md` / `docs/ARCHITECTURE.md`
- [x] 实测 codex/hermes workspace 环境(见 ADR-004)
- [x] 确认部署形态:codex workspace + docker(ADR-004)
- [x] 新建 hermes workspace,实测:/data 1.0T 空(剩 1023G)、systemd、sudo 完整 caps、无 docker
- [x] hermes 建实验目录 `/data/xcvat/{cvat,cvat-data,logs,scripts}`
- [x] 测通 codex→hermes ssh(agent forwarding),hermes→codex 不通(publickey)
- [x] rsync 复制 codex `/data/env`(29G)→ hermes,保持同路径
- [x] 修复 conda 路径硬编码:建软链 `/data/miniconda3 -> /data/env/miniconda3`
- [x] 验证 hermes conda det 环境:nori2/refile/brainpp.oss/meghair 全部 import OK

## 下一步

- [ ] hermes 安装 docker + docker compose(systemd 托管)
- [ ] 推 CVAT 源码到 hermes `/data/xcvat/cvat`(本地 131M + .git 367M)
- [ ] 验证标注员网络可达性(`100.121.177.210:8080` 或 SSH 转发 / Traefik)
- [ ] 起最小 CVAT(`docker compose up -d`),浏览器打开登录页
- [ ] nori → CVAT 数据导入桥(ADR 待立)
- [ ] 在 GitHub fork cvat-ai/cvat,调整 remote(ADR-003 执行)
- [ ] 建立长期魔改集成分支

## 上次会话摘要

**2026-07-27**:校验 CVAT clone 完整性。确认项目方向 —— fork 魔改 CVAT,独立于 xlabel。建立记忆设施。读取 ssh-server / odgt-data-upload skill,摸清 Brain++ 平台。实测 codex workspace:sudo 完整 caps、systemd、mount/overlay 支持 → docker 可起。用户澄清 workspace 持久。决策方案 B:codex workspace 装 docker 跑 CVAT(ADR-004)。随后用户新建 hermes workspace(/data 1.0T 空),定 CVAT+nori 桥接定位、rsync 复制环境。完成:建实验目录 `/data/xcvat/`、测通 codex→hermes ssh、rsync 29G conda 环境、修复路径硬编码(建 `/data/miniconda3` 软链)、验证 nori2/refile/brainpp.oss/meghair 全 import OK。
