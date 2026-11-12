# ux-refine

> 已有产品 / 平台系统的前端 UI 与交互体验优化 —— 一个 Claude Code / Agent Skill。

功能模块一个个叠上去，每次都局部合理，叠在一起就乱了：菜单越来越长、同类页面各写各的、按钮样式五六种、
高频操作要点好多步、状态反馈时有时无。这个技能帮你**看清全貌、给出有依据的方案、和你一起拍板、按计划落地**。

## 工作方式

1. **开场选项菜单**：一调起就给选项——优化方向（导航 / 一致性 / 流程效率 / 反馈状态 / 表单 / 文案 / 响应式）、范围、做到哪一步（完整流程 / 只诊断 / 到计划为止）、用户与高频任务。
2. **侦察**：技术栈、页面地图、组件库与样式体系、怎么跑起来。
3. **取证**：读代码 + Playwright 渲染截图 + 高频任务逐步走查 + 你提供的素材 + 业界对标（引用实际查证），每条结论都带截图或 `文件:行号`。
4. **诊断**：贯穿信号「提醒是设计的补丁」+ 九个透镜（信息架构、视觉层次、一致性、流程效率、反馈状态、表单、防错、文案、响应式与可访问性），分级排序。
5. **方案共创**：先给全景，再对有取舍的点逐项确认，布局类选择附 ASCII 线框图对比。
6. **执行计划**：效仿 plan 模式写成 `.ux-refine/plan.md`，**批准前只读不改代码**。
7. **分批执行**：每批构建 / 测试通过 + 改前改后截图对比，你验收后再进下一批。

## 安装

```bash
ln -s /path/to/ux-refine ~/.claude/skills/ux-refine
```

依赖：
- Python 3。`style_inventory.py` 仅用标准库。
- 截图走查需要 Playwright：`pip install playwright && playwright install chromium`。
  没装时技能会退化为代码侧取证 + 你提供的截图。

## 怎么用

- 「我们的运营后台越来越难用了，帮我优化一下体验」
- 「订单和用户两个列表页长得完全不一样，统一一下」
- 「菜单太长了新人找不到功能，重新梳理一下导航」
- `/ux-refine`

## 目录

```
SKILL.md                    流程与闸门
references/recon.md         侦察与截图走查方法
references/lenses.md        「提醒是设计的补丁」信号 + 九个诊断透镜
references/patterns.md      最佳实践方案模式库
references/plan-template.md findings.md / plan.md 模板
scripts/style_inventory.py  样式取值发散度统计
scripts/ui_snapshot.py      多路由 × 多视口截图 + 控制台报错采集
scripts/walk_task.py        按 JSON 步骤走查任务路径，输出步数/跳转/对话框/报错步骤表
```

过程产物写在被优化项目的 `.ux-refine/` 目录下（截图、问题清单、执行计划），建议加入 `.gitignore`。
