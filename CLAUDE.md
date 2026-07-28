# CLAUDE.md — xcvat 项目宪章

> 本文件每次会话自动加载,是项目的"常驻记忆"。fork 自 cvat-ai/cvat@v2.71.0,**独立于 xlabel 项目**。核心观点稳定后演进;详细架构见 `docs/ARCHITECTURE.md`,当前进度见 `docs/STATE.md`,决策与教训见 `docs/DECISIONS.md`。

## 项目概述

**xcvat**(工作代号,待正式命名)= 基于 CVAT 的 fork 二次开发项目。以 CVAT(自托管标注平台,MIT)为底座做深度定制,适配自有的标注场景与工作流。

定位:**fork 魔改** —— 站在 CVAT 肩膀上,保留 upstream 同步能力,不推倒重来。

> 与 xlabel 的关系:两个项目**并行独立**。xlabel 是"X-AnyLabeling + CVAT 对接工作流"(消费侧,把 CVAT 当外部工具);xcvat 是"CVAT 本体的深度定制"(产品侧,改 CVAT 源码)。互不耦合,仅在全局 memory 互留指针。

## 核心观点(不可妥协)

1. **fork 而非重写** —— 能改则改,不能改则包一层;不重造 CVAT 已有的标注/协作/视频能力
2. **upstream 同步优先** —— 自己的改动隔离在明确边界内,定期 merge upstream,避免分叉失控
3. **改动可追溯** —— 每处魔改都在 `docs/DECISIONS.md` 留 ADR,说明 why 与升级影响
4. **不破坏 CVAT 契约** —— REST API / 数据格式 / 镜像构建流程保持兼容,便于 upstream 升级时低摩擦合并

## fork 基线

| 项 | 值 |
|---|---|
| upstream | https://github.com/cvat-ai/cvat.git |
| 基线 tag | v2.71.0 |
| 基线 commit | 170ce0ad7(develop) |
| 当前 remote | origin → upstream(待调整为自有 fork,见 ADR-003) |
| 子模块 | site/themes/docsy(文档站主题,未初始化,跑 CVAT 不需要) |

## upstream 同步策略(详见 docs/DECISIONS.md · ADR-003)

- origin 指向自有 GitHub fork(待建)
- 新增 upstream remote 指向 cvat-ai/cvat
- 长期魔改集成分支承载所有定制,定期 `merge upstream/develop`
- 魔改文件头标注 `// xcvat: <原因>`,便于升级时定位冲突

## 文档体系

- `docs/STATE.md` — 当前进度(每次会话结束更新)
- `docs/DECISIONS.md` — ADR 决策日志(新决策先入此)
- `docs/ARCHITECTURE.md` — CVAT 架构概览 + 魔改切入点

## 工作约定

- 文档与注释用**中文**
- 新决策先记入 `docs/DECISIONS.md`(ADR 风格),重要教训定期蒸馏回本文件核心观点
- 每次会话结束更新 `docs/STATE.md`
- 改 CVAT 源码前,先评估对 upstream 升级的影响,记入 ADR;优先用扩展点(plugin / hook / 中间件 / 覆盖层)而非改核心
- 不修改 `site/` 文档站(非本项目关注);不擅自改 git remote(等 ADR-003 执行)

## 三大避坑(务必牢记)

1. **别让 fork 分叉失控** —— 不定期 merge upstream,半年后合并成本指数级上升。纪律性同步。
2. **别在 CVAT 核心契约上魔改** —— 改 REST API / 数据模型会断掉 SDK / CLI / UI 的兼容性,升级成本最高。优先用扩展点。
3. **别忽略 LGPL 组件** —— CVAT 主体 MIT,但 FFmpeg 等 LGPL,分发镜像时注意合规。

## 参考

- upstream 仓库:https://github.com/cvat-ai/cvat
- 架构详图:`docs/ARCHITECTURE.md`
- 决策日志:`docs/DECISIONS.md`
- 当前状态:`docs/STATE.md`
- 兄弟项目:xlabel(`D:\program\cursor_test\xlabel`,CVAT 对接工作流)
