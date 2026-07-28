# 决策日志(ADR)

> Architecture Decision Records。每条记录一个不可逆或影响深远的决策,含背景、决策、理由、后果。新决策追加到末尾。

---

## ADR-001 fork 魔改 CVAT,而非"部署+对接"或"全新重写"

- **日期**:2026-07-27
- **状态**:已决

**背景**:需要在 CVAT 基础上构建自己的标注项目。三条路径:
1. fork 魔改 —— 改 CVAT 源码,保留 upstream 同步
2. 部署 + 外部对接 —— 不改源码,在外部写适配层(符合 xlabel 宪章 P2 设计)
3. 全新重写 —— 从零做起

**决策**:选 1 —— fork 魔改。

**理由**:
- 有深度定制需求(具体场景待明确),部署+对接的扩展点不够
- 全新重写浪费 CVAT 已有的成熟标注/协作/视频/SDK 能力
- fork 既能深度改,又能吃 upstream 的持续维护红利

**后果**:
- 承担 upstream 同步成本(见 ADR-003)
- 需建立分支策略与改动追溯纪律
- 每处核心魔改必须留 ADR

---

## ADR-002 独立于 xlabel 项目

- **日期**:2026-07-27
- **状态**:已决

**背景**:已有 xlabel 项目(`D:\program\cursor_test\xlabel`,X-AnyLabeling + CVAT 对接工作流),其 P2 阶段涉及 CVAT。

**决策**:本 fork 项目独立于 xlabel,有自己的宪章与文档体系,不纳入 xlabel 文档。

**理由**:
- 用户明确为独立新项目
- 避免耦合:xlabel 的 CVAT 对接是**消费侧**(把 CVAT 当外部工具),本 fork 是**产品侧**(改 CVAT 本体)
- 职责清晰,各自演进

**后果**:
- 两个项目并行,各有 CLAUDE.md / docs/
- 在全局 memory 互留指针保持 awareness
- 未来若需联动,通过文件系统 / API 契约交互,不互嵌

---

## ADR-003 upstream 同步策略

- **日期**:2026-07-27
- **状态**:✅ 已执行(2026-07-28)

**背景**:fork 魔改必须规划 upstream 同步,否则分叉失控,半年后合并成本指数级上升。

**决策**:
1. 在 GitHub fork `cvat-ai/cvat` 到用户账号
2. remote 调整:
   - `origin` → 用户自有 fork(日常 push)
   - 新增 `upstream` → cvat-ai/cvat(只拉不推)
3. 建立长期魔改集成分支(命名待定,候选 `xcvat/main` 或 `fork/main`),所有定制在此
4. 同步节奏:定期 `git fetch upstream && git merge upstream/develop` 进集成分支
5. 魔改文件在头部标注 `# xcvat: <原因>`,便于升级时定位冲突点
6. 核心 model/API 的魔改单独留 ADR,评估升级影响

**执行结果(2026-07-28)**:
- GitHub fork:`https://github.com/qinliumu/cvat`(用户 qinliumu)
- hermes remote:`origin` → `git@github.com:qinliumu/cvat.git`(SSH),`upstream` → `https://github.com/cvat-ai/cvat.git`
- 魔改集成分支:`xcvat/main`(基于 develop@170ce0ad7),已 push 到 fork
- 首个 commit:`b2c081057 docs: add xcvat project charter and memory infrastructure`(CLAUDE.md + docs/)
- SSH 认证:hermes 生成 ed25519 key,公钥已加到 GitHub;`~/.ssh/config` 配 `ProxyCommand nc -X 5 -x 127.0.0.1:1080`(github SSH 走 xray socks 1080,因 hermes 无公网)

**配套基础设施**:
- git http.proxy 已 unset(SSH 方式不需要 http 代理)
- `~/.ssh/config` 的 github.com 走 xray socks5(1080),StrictHostKeyChecking accept-new
- `.env`、`cvat-tunnel.bat` 被 .gitignore 忽略(`/*env*/`、`/.*env*`),本地配置不入库,符合预期

**后果**:
- upstream 升级时合并成本可控(文件级冲突可定位)
- 需纪律性定期同步(建议每月或每个 upstream release)
- ✅ 已执行

---

## ADR-004 CVAT 部署形态:Brain++ codex workspace + docker

- **日期**:2026-07-27
- **状态**:已决(部署形态);具体实施待 ADR-005+

**背景**:用户原计划"在 Brain++ 上建一台带 docker 的服务器跑 CVAT"。经实测与用户澄清,确定在 codex workspace 上直接部署。

**关键澄清(用户纠正)**:
- **workspace 是持久的** —— 数据不会因不活跃被删(Brain++ 横幅清理的是长期**关闭**的 workspace,持续运行的不受影响)
- **rlaunch 节点是临时计算资源**,与 workspace 底层相同但管理不同
- 此前 ADR-004 草稿把 workspace 当成"会被清理的 pod"是误判,已纠正

**codex workspace 实测环境**:

| 项 | 值 | 对 CVAT 的意义 |
|---|---|---|
| docker / docker compose | 未安装 | 需安装;apt 可用,可装 |
| systemd | ✅ PID 1 是 systemd | **可管理 docker daemon 为系统服务** |
| sudo | ✅ 免密,sudo 后 `CapEff: 3fffffffff`(完整 caps) | **能起 docker daemon**(关键) |
| mount 能力 | ✅ sudo 下 mount tmpfs 成功 | overlay2 存储驱动可用 |
| overlay 文件系统 | ✅ 内核支持 | docker 默认存储驱动 OK |
| `/data` | 1.0T,**剩 46G(96% 满)** | 可写但空间紧张,需清理或限定 CVAT 数据量 |
| `/kubebrain` | 893G 但**只读** | 不能当数据盘 |
| 内存 / CPU | 99G / 49 核 | 充足,CVAT 全栈够用 |
| GPU | workspace 无 | serverless AI 标注需另起 rlaunch GPU 作业 |
| 本机 IP | `100.121.177.210`(eth0 内网) | 标注员浏览器可达性待验证(见下) |
| localhost:8080 | 空闲 | 端口可用 |
| nori / s3 数据 | `s3://jiigan-odt/`,det 环境可访问 | CVAT 不能直读 nori,需建桥(ADR 待立) |

**决策**:在 codex workspace 上安装 docker + docker compose,以标准 `docker-compose.yml` 部署 CVAT。

**部署要点(实施时遵循)**:
1. **数据卷外挂到 /data 下独立目录**(如 `/data/cvat/`),不混入 `/data/projects/`;并**限定用量**或先清理 /data(46G 对 CVAT 镜像+数据偏紧)
2. docker daemon 用 systemd 托管,workspace 重启后自恢复
3. PostgreSQL 数据、标注数据、上传图片都放 /data 持久路径,**不放容器内或 /tmp**
4. serverless AI 标注的 GPU 推理,通过 rlaunch GPU 作业或 Nuclio 远程函数提供,不依赖 workspace 本机 GPU
5. 标注员访问:需验证 `100.121.177.210:8080` 对标注员网络是否可达;不可达则走 SSH 端口转发或 Traefik + 域名

**未决子项(各自 ADR)**:
- [ ] nori → CVAT 数据导入桥(对应 xlabel"格式桥"思路,这里是 nori/s3 → CVAT)
- [ ] /data 空间规划(清理 vs 限定数据量 vs 申请扩容)
- [ ] 标注员网络可达性方案(直连 / 端口转发 / Traefik)
- [ ] serverless GPU 推理与 rlaunch 的打通方式

---

## 待决(TBD)

- 项目正式代号(暂用 `xcvat`)
- 具体定制场景与首批魔改点
- 长期集成分支命名
- GitHub fork 账号
