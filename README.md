# ZCode Subagents

> Model-routed subagents and a GPT-6 Astra–tuned global instruction file for ZCode.

把一套**按职责分工、各自绑定模型和推理档位**的子智能体配置，装到任意一台 ZCode 上。
A reusable set of model-routed ZCode subagents, plus the global `AGENTS.md` they run under.

**给另一台电脑的 ZCode 用**：直接把这个仓库地址丢给它，让它读 [`docs/INSTALL.md`](docs/INSTALL.md) 并按步骤配置。
**For another ZCode instance**: point it at this repository and tell it to follow [`docs/INSTALL.md`](docs/INSTALL.md).

---

## 这套配置解决什么问题 / What this solves

多数 ZCode 子智能体配置只换模型名，不区分职责、不约束权限，也不控制推理档位。结果是：搜索和深度推理用同一个档位，审查角色能顺手改代码，全局规则和运行时注入的角色说明互相打架。

This configuration binds **role → model → reasoning level → write permission** together, and keeps the global instruction file free of anything the runtime already injects.

## 角色一览 / Roles

| 角色 Role | 职责 Responsibility | 默认模型 Default model | 档位 Level | 写入权限 Write |
| --- | --- | --- | --- | --- |
| `architect` | 关键架构、公共接口、数据模型、安全边界 | GPT-6 Astra | `xhigh` | 只读 read-only |
| `builder` | 关键 UI/Web 页面、公共视觉组件、复杂交互 | GPT-6 Astra | `xhigh` | 可写 yes |
| `verifier` | 测试、构建、复现、日志与浏览器验证 | GPT-5.6 Luna | `max` | 不写源码 no source |
| `reviewer` | 高风险、跨模块、数据敏感变更审查 | Kimi Coding `k3` | `max` | 只读 read-only |
| `expert` | 难定位根因、复杂推理、关键跨模块实现 | GPT-6 Astra | `xhigh` | 可写 yes |
| `reviewer-fallback` | 主审查模型不可用时接替 | GPT-6 Astra | `xhigh` | 只读 read-only |

内置角色 `Explore` 与 `general-purpose` 只覆盖模型和档位，提示词保持 ZCode 原版。
The built-in `Explore` and `general-purpose` agents keep their original prompts; only their model and reasoning level are set.

模型名按本机可用性自动解析，可通过 `--routes` 覆盖。见 [`docs/INSTALL.md`](docs/INSTALL.md)。
Model names resolve against the local ZCode install and can be overridden. See [`docs/INSTALL.md`](docs/INSTALL.md).

## 快速开始 / Quick start

```bash
git clone https://github.com/kingmaozi/zcode-subagents.git
cd zcode-subagents

python3 scripts/install.py --list-models   # 看本机有哪些模型
python3 scripts/install.py                 # 预演，不改任何文件
python3 scripts/install.py --apply         # 确认后写入
```

安装器只用 Python 标准库，不需要 `pip install`。**默认永远是预演**，加 `--apply` 才落盘。
Standard library only. The default is always a dry run.

## 语言约定 / Language convention

- `description` 用中文 —— 给人看，在主会话选择角色时一眼看清用途。
- 系统提示词正文用英文 —— 给模型看，短句、无歧义、无冲突。
- 每个角色要求**用简体中文返回结论**，代码、命令、路径保持原样。

`description` in Chinese for humans; system prompt body in English for the model; answers back in Chinese. English is not inherently more obedient — clarity and non-conflicting rules matter far more. The split just lets each reader use the language it handles best.

## 全局规则为什么长这样 / Why the global file looks like this

`global/AGENTS.md` 针对 **GPT-6 Astra** 的已知行为做了处理，这几条来自 OpenAI 官方模型指南：

| Astra 的已知倾向 | 规则里的应对 |
| --- | --- |
| 意图不完全明确时倾向停下来提问，可能把「帮我做 X」当成询问而不是指令 | 明确「请求隐含行动就是执行指令」，澄清限制在「答案会改变结果」的问题上 |
| 对 `AGENTS.md`、技能文件里的指令尤其敏感，冲突的指引会让它提前停下 | 固定优先级：用户指令 > 全局规则 > 项目 AGENTS.md > 技能；停顿前必须指出是哪条规则 |
| 可能比期望更少派发子智能体 | 明确何时该并行派发，以及派发时必须交代什么 |
| 偏长、偏格式化，容易跨会话重复同样的措辞 | 要求按请求选择篇幅与格式，不默认堆列表和表格 |
| 小任务上可能验证过度 | 按变更风险选择验证范围，不机械跑全量测试 |

来源：OpenAI 官方文档 `developers.openai.com` 的 GPT-6 Astra 模型指南与提示工程指南。

**关键取舍：全局规则里不写子智能体角色表。** 角色说明由运行时逐个注入到子智能体，在全局文件里再写一遍会造成两处说明不一致，而 Astra 对这类冲突特别敏感。全局文件只保留跨项目默认行为、派发纪律、验证纪律和配置边界。

`global/AGENTS.md` is tuned for GPT-6 Astra's documented tendencies — over-asking, sensitivity to conflicting instruction files, under-delegation, verbose formatting, and over-testing small changes. It deliberately contains **no subagent role table**, because ZCode injects each role's instructions at runtime and restating them risks contradictions.

## 可选依赖 / Optional dependency

只读角色的工具白名单里带有四个 `mcp__codegraph__*` 检索工具。它们只在本机配置了 `codegraph` MCP server 时生效；未配置时会被静默忽略，不影响角色加载。详见 [`docs/INSTALL.md`](docs/INSTALL.md)。

## 目录结构 / Layout

```
agents/          六个角色模板，model 用 {{MODEL_REF}} 占位
global/AGENTS.md 全局协作规则模板（英文，给主会话用）
scripts/install.py   安装器：预演、按模型解析、备份、原子写入
docs/INSTALL.md  完整安装与验证步骤（中文）
tests/           安装器测试
```

## 验证 / Verify

配置写好了不等于生效。按顺序确认：

1. 新建会话调用 `verifier`，确认角色被加载（自定义角色不热加载）。
2. 在本机运行记录里核对实际使用的 provider、模型和推理参数 —— 不要相信角色的自我说明。
3. 确认只读角色的写入限制符合预期。

跑测试：

```bash
python3 -m unittest discover -s tests -v
```

## 安全 / Security

- 仓库内**没有任何密钥**。角色模板用 `{{MODEL_REF}}` 占位，本机的 `custom:<providerId>:<modelId>` 由安装器在本地解析。
- 安装器**不修改** `v2/config.json`，不写凭据，不改主会话模型，不重启 ZCode。
- 写入前在 `~/.zcode/backups/` 留带时间戳的备份。
- 不提交 `.env`、密钥、个人数据或本地数据库。

No secrets are committed. Model references are resolved locally; the installer never touches credentials or the main session's model.

## 已知限制 / Known limitations

- **不是热加载**：改完角色文件需新建会话或重启 ZCode。
- **只读不是沙箱**：只读角色保留 `Bash` 用于检索，靠工具白名单和行为约束限制，不是操作系统级隔离。
- **`providerId` 不能跨机器复制**：每台电脑的 provider UUID 不同。
- **中转站模型名不等于官方直连**：运行记录只能证明本机向哪个服务发了哪个模型名，不代表上游实现或计算预算。
- **推理档位需要真实参数映射**：在 ZCode 里列出某档位，不保证请求真的带上对应参数。
- **`reviewer-fallback` 不是自动降级**：主审查失败时需要显式调用。

## License

MIT
