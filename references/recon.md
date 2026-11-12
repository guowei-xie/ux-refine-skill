# 侦察与取证方法

目录
1. 识别技术栈与组件库
2. 找路由与菜单
3. 页面归类
4. 样式体系盘点
5. 把应用跑起来
6. 截图走查
7. 任务路径走查（walk_task.py）
8. inventory.md 模板

---

## 1. 识别技术栈与组件库

先读 `package.json`（monorepo 看 `apps/*`、`packages/*`）：
- 框架：`react` / `vue` / `next` / `nuxt` / `@angular/core` / `svelte` / `umi` / `@umijs/max` / `vite`。
- 组件库：`antd`、`@ant-design/pro-components`、`element-plus` / `element-ui`、`@arco-design/*`、
  `tdesign-*`、`@mui/material`、`@chakra-ui/*`、`naive-ui`、`vant`、`shadcn`（看 `components/ui/`）、`tailwindcss`。
- 同时出现两个组件库，或组件库大版本混用（antd 3 与 4），本身就是一致性问题的强信号，记下来。

## 2. 找路由与菜单

| 技术栈 | 路由 / 菜单通常在哪 |
|---|---|
| Umi / Ant Design Pro | `config/routes.ts`、`config/config.ts` 的 `routes`；菜单由路由的 `name`、`icon` 生成 |
| React Router | `createBrowserRouter`、`<Routes>`、`routes.tsx`；菜单常另有 `menu.ts` / `menuConfig` |
| Next.js | `app/` 或 `pages/` 目录结构即路由；菜单在 layout 或 sidebar 组件里 |
| Vue Router | `src/router/index.ts`、`src/router/modules/*`；`meta.title` / `meta.hidden` 控制菜单 |
| Nuxt | `pages/` 目录结构 |
| Angular | `*-routing.module.ts`、`app.routes.ts` |

菜单项也可能来自后端接口（按权限下发），这时用 grep 找 `menu`、`permission`、`getMenus`，
并请用户提供一个典型角色的菜单截图或接口返回。

记录：页面总数、菜单各级数量、最大深度、隐藏路由数量、名称带 v2 / new / old 的路由。

## 3. 页面归类

按页面类型归类（列表 / 详情 / 表单 / 看板 / 设置 / 其他），每类记下「有几种不同写法」：
比如列表页里有的用 ProTable、有的用 Table + 自写筛选、有的用自研 DataGrid。
抽 2–3 个同类页面对比结构，是发现一致性问题最快的方法。

## 4. 样式体系盘点

```bash
python3 <skill>/scripts/style_inventory.py src --out .ux-refine/style-inventory.md
```

同时找：主题与 token 文件（`theme.ts`、`variables.less`、`tokens.css`、`tailwind.config.*`）、
全局样式、组件库主题配置（`ConfigProvider theme`、`createTheme`）。
重点看 token 引用和字面量的比例：token 定义了却大量写死，说明规范有但没被遵守。

## 5. 把应用跑起来

- 启动命令看 `package.json` 的 `scripts`（`dev` / `start` / `serve`）与 README。依赖未安装时先问用户
  是否允许 `npm install`（会改动 `node_modules`，通常可接受，但锁文件变化要提醒）。
- 后台运行开发服务器，记下端口；结束时停掉，不要留下常驻进程。
- 依赖后端时：问用户有没有测试环境地址、mock 开关（`MOCK=true`、`mock/` 目录）、或本地后端。
- 需要登录时：先尝试 `ui_snapshot.py --save-auth`，让用户在弹出的浏览器里手动登录，保存的登录态文件
  放在 `.ux-refine/auth.json`，提醒用户这个文件含 cookie，不能提交。不要让用户在对话里贴密码。
- 实在跑不起来：如实说明，改为请用户提供关键页面截图，或只做代码侧取证，并在 findings 里注明证据范围受限。

## 6. 截图走查

```bash
# routes.txt 每行「名称 路由」，按页面地图挑代表性页面：每类页面至少 2 个，高频页面全部
python3 <skill>/scripts/ui_snapshot.py --base-url http://localhost:8000 \
  --routes-file .ux-refine/routes.txt --storage-state .ux-refine/auth.json \
  --out .ux-refine/screenshots/before
```

- 默认视口是 1440×900 和 1366×768，B 端系统的主力屏幕。有移动端用户时加 `mobile`。
- 看 `report.json`：`page_errors` / `console` 错误、`failed_requests`、`horizontal_overflow`、
  被重定向到登录页的 `note`、`settled_ms` 明显偏长的页面。
- **用 Read 打开截图逐张看**。脚本只负责采集，判断要靠你看：页面第一眼的焦点、主操作位置、
  信息密度、同类页面放在一起时的差异。
- 截图数量多时（> 30 张），先看每类的代表页，再针对发现的问题去看其他页确认是否普遍。
- 需要截特定状态（弹窗打开、表单报错、空列表）时，用 `walk_task.py` 写几步操作再加 `screenshot`，见下一节。

## 7. 任务路径走查

对用户确认过的高频任务（或从路由与菜单推断出的核心任务），用 `walk_task.py` 走一遍，不要每次手写 Playwright 脚本。
把每个任务写成一份步骤文件 `.ux-refine/tasks.json`（格式见脚本开头的说明），然后：

```bash
python3 <skill>/scripts/walk_task.py .ux-refine/tasks.json --out .ux-refine/walk/before
```

步骤文件的写法要点：
- 按**真实用户**的走法写：从他通常进入的页面出发（工作台、菜单），而不是直接打开目标页的深链接。
  这样步数和跳转次数才反映真实成本。
- 关键的「这里能不能点 / 有没有 / 显示的是什么」用 `check` 观察，并写上 `expect` 表达期望行为，
  例如 `{"do": "check", "target": "text=待审核", "probe": "is_link", "expect": true}`。不符合期望的步骤会标 ✗，直接成为证据。
- 可能不存在的入口（例如「下架」按钮）加 `"optional": true`，找不到时只标「–」，不中断判断。
- 需要特定状态（弹窗、表单报错、空列表）时也用它：点开弹窗，再加一步 `screenshot`。

输出的 `walk.md` 有两层：
- 汇总表：每个任务的用户操作数、跳转次数、原生对话框、报错、失败步骤。
- 每步明细：动作、结果、发生了什么（跳转、弹出的对话框原文、控制台报错、失败请求），以及对应截图。

它直接作为「任务流程效率」「反馈与状态」透镜的证据。截图要用 Read 打开看，脚本只负责记录发生了什么，
犹豫点、信息是否好找，要靠你判断后补进 findings。

**改后验收**用同一份步骤文件再跑一次：

```bash
python3 <skill>/scripts/walk_task.py .ux-refine/tasks.json --out .ux-refine/walk/after
```

如果改动改变了操作路径（比如审核挪到了列表行内），就为新路径另写一个任务，和旧路径的步数放在一起对比，
例如「审核一单：5 步 2 次跳转 → 2 步 0 次跳转」。这种对比是最直观的验收证据。

## 8. inventory.md 模板

```markdown
# 页面地图与样式体系 · <项目名>

## 技术栈
框架 / 组件库及版本 / 样式方案 / 主题与 token 文件位置

## 怎么跑起来
启动命令、端口、登录方式、后端依赖、已知限制

## 路由与菜单
页面总数 N；一级菜单 N 项；最大深度 N；隐藏路由 N
（按菜单分组列出页面：名称 · 路由 · 页面类型 · 文件位置）

## 页面类型与写法
| 类型 | 页面数 | 写法种数 | 代表文件 |

## 样式体系
token 文件；style_inventory 摘要（各类取值数量）；与组件库主题的关系

## 高频任务
用户确认的 / 推断的（待确认）
```
