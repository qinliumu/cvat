# 项目状态

> 最近更新:2026-07-28

## 当前任务

阶段 4 part 2(后端 endpoint)完成。下一步:前端 React 按钮集成(part 3)。

## 已完成

- [x] CVAT 部署到 hermes(18 容器,admin/admin,SSH 隧道 localhost:8080)
- [x] 阶段 0:GitHub fork(qinliumu/cvat)+ xcvat/main 分支 + SSH key(走 xray socks)
- [x] 阶段 1:ODGT format(`formats/odgt.py` export+import + registry 注册 + volume 挂载持久化)
- [x] 阶段 1 端到端:task 5(2图2框)→ 导出 ODGT → JSON-lines 正确(box xywh + tag + width/height)
- [x] 阶段 2:`nori_to_cvat.py` 导入桥接(ODGT → nori 拉图 → CVAT API 建 task + 上传 + 灌标注),本地模式往返验证通过
- [x] 阶段 3:`cvat_to_nori.py` 导出桥接(CVAT task → ODGT zip → build_online_dataset → s3 nori+ODGT),真实 DataID + 正确 GT
- [x] odgt.py save_images 修复(用 dump_media_files frame provider 取真实图片)
- [x] 阶段 4 part 1:sidecar HTTP 服务(`sidecar.py` + systemd `xcvat-sidecar.service`,/import /export /status)
- [x] 阶段 4 part 2:CVAT 后端 `xcvat_bridge` app(/api/xcvat/import|export|status,转发 sidecar)

## CVAT API 关键(实测,给前端用)

- CSRF:GET /api/auth/rules → 登录 → X-CSRFToken header
- xcvat endpoint:`POST /api/xcvat/export {task_id, name, category}` → 202 {job_id}
- 轮询:`GET /api/xcvat/status/<job_id>` → {status: running|done|failed, nori, odgt}

## 下一步:前端 React 按钮(part 3)

- 在 cvat-ui 任务/job 页 actions 菜单加"Export to nori/ODGT"项
- 参考:`components/jobs-page/actions-menu-items.tsx`、`actions/export-actions.ts`
- 调 `/api/xcvat/export`,轮询 status,显示进度
- 需要 npm build + rebuild cvat-ui 镜像(慢)

## 已知约束

- nori.Fetcher / 加速在 workspace 不工作 → 用 rlaunch pod(odgt skill 记的约束)
- cvat_to_nori.py 用 `--no_accelerate --no_verify`(workspace 跑),pod 里加速用 accelerate_multi.py
- sidecar 监听 0.0.0.0:9580(容器经 172.17.0.1 访问)

## 环境关键事实(hermes)

- **网络**:IP 100.123.228.217,Brain++ 内网;办公网经 SSH 隧道访问 localhost:8080
- **CVAT**:`.env` CVAT_VERSION=v2.71.0 + CVAT_HOST=localhost,18 容器,源码 volume 挂载(/data/xcvat/cvat/cvat → /home/django/cvat)
- **docker**:29.1.3,iptables-legacy,data-root=/data/docker-data,HTTP_PROXY=xray 1081
- **xray**:systemd xray-proxy.service,docker 域名走 vless 翻墙
- **conda det**:已就绪,nori2/refile/brainpp.oss/meghair import OK
- **sidecar**:systemd xcvat-sidecar.service,0.0.0.0:9580,det env python
- **git**:origin→git@github.com:qinliumu/cvat.git(SSH via xray socks),upstream→cvat-ai/cvat,分支 xcvat/main

## 上次会话摘要

**2026-07-28**:完成阶段 2-4 part 2。阶段 2 nori_to_cvat.py(ODGT→CVAT,本地往返验证)。阶段 3 cvat_to_nori.py(CVAT→s3 nori+ODGT,真实 DataID),修 odgt.py save_images(dump_media_files)。阶段 4 part 1 sidecar HTTP 服务 + systemd。part 2 xcvat_bridge Django app(/api/xcvat/* 转发 sidecar),验证 POST /api/xcvat/export 202 + status 轮询。**端到端打通**:CVAT API → xcvat_bridge → sidecar → cvat_to_nori → s3。前端 React 按钮待做(part 3)。fork 9 commits。
