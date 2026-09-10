# 跨电脑配置 ZCode 子智能体

这份说明写给要**在另一台电脑的 ZCode 上重现同一套子智能体分工**的人，也写给直接读仓库的 AI。整套配置只有三步：装角色文件、指定模型、验证真的生效。不需要修改应用本体。

## 这套配置是什么

六个自定义子智能体，各自绑定一个模型和推理档位，边界写在各自的提示词里：

| 角色 | 职责 | 默认模型 | 默认档位 | 写入权限 |
| --- | --- | --- | --- | --- |
| `architect` | 关键架构、公共接口、数据模型、协议、安全边界 | GPT-6 Astra | xhigh | 只读 |
| `builder` | 关键 UI/Web 页面、公共视觉组件、复杂交互 | GPT-6 Astra | xhigh | 可写 |
| `verifier` | 测试、构建、复现、日志与浏览器验证 | GPT-5.6 Luna | max | 不写源码 |
| `reviewer` | 高风险、跨模块、数据敏感变更审查 | Kimi Coding `k3` | max | 只读 |
| `expert` | 难定位根因、复杂推理、关键跨模块实现 | GPT-6 Astra | xhigh | 可写 |
| `reviewer-fallback` | 主审查模型不可用时接替 | GPT-6 Astra | xhigh | 只读 |

另外两个是 ZCode 内置角色，本仓库不动其提示词，只覆盖模型：

| 内置角色 | 职责 | 默认模型 | 默认档位 |
| --- | --- | --- | --- |
| `Explore` | 只读搜索、定位调用链 | GPT-5.6 Luna | max |
| `general-purpose` | 普通实现与综合任务 | GPT-5.6 Luna | max |

ZCode 内置角色只有这两个。不要照搬其他工具的 `default`、`worker` 等角色名——它们不是 ZCode 的注册名，ZCode 只认实际存在的 `subagent_type`。

## 语言约定

- `description` 用中文，给人看：在主会话选择子智能体时一眼知道这个角色是干什么的。
- 系统提示词正文用英文，给模型看：职责、禁止事项、交付格式写成短句，减少歧义。
- 每个角色最后一条都要求**用简体中文返回结论**，代码、标识符、命令、路径保持原样。

英文不会让模型「更听话」。规则可靠与否取决于是否清晰、是否互相冲突，以及权限是否真正受限。中英混排的唯一好处是：人看中文、模型读英文，各自都省事。

## 步骤一：确认本机模型名

角色绑定的是 `custom:<providerId>:<modelId>`，其中 `providerId` 是本机 ZCode 生成的 UUID，**每台电脑都不同**，所以仓库里的模板用占位符 `{{MODEL_REF}}`，安装时替换。

先列出本机可用的 provider 与模型：

```bash
python3 scripts/install.py --list-models
```

输出只包含 provider 名称、provider ID 和模型引用，**不会打印 API key 或配置原文**。确认你能看到类似：

```
provider  your-openai-compatible  (a1b2c3d4-....)
  custom:a1b2c3d4-....:gpt-6-astra
  custom:a1b2c3d4-....:gpt-5.6-luna
provider  kimi-coding           (e5f6a7b8-....)
  custom:e5f6a7b8-....:k3
```

如果缺少 Astra、Luna 或 K3，先在 ZCode 里 **Settings → Models** 添加对应供应商和模型，再继续。`--list-models` 只读现有配置，不会替你新建模型。

## 步骤二：预演，再写入

**默认是预演（dry-run），不会改任何文件。**

```bash
python3 scripts/install.py
```

确认输出里六个角色各自解析到的模型和档位都正确，再实际写入：

```bash
python3 scripts/install.py --apply
```

安装器会做这些事：

1. 读取本机 `~/.zcode/v2/config.json`，在**已启用的 provider** 中按模型 ID 唯一匹配，算出每个角色的模型引用。
2. 写入六个 `~/.zcode/agents/<name>.md`。
3. 只在 `~/.zcode/v2/agents-state.json` 里合并内置角色 `Explore`、`general-purpose` 的模型与档位覆盖，保留该文件的其他字段和停用列表。
4. 在 `~/.zcode/backups/` 下建带时间戳的独立备份，权限 0700，文件 0600。
5. 写入前先做全部预检，任何一项不通过就整体停止，不会写一半。

它**不会**碰 `v2/config.json`、不会写任何凭据、不会修改主会话的模型和档位、不会重启 ZCode。

常用参数：

| 参数 | 作用 |
| --- | --- |
| `--zcode-home PATH` | 指定目标 ZCode 目录，默认 `~/.zcode`；测试用临时目录时必须传 |
| `--routes PATH` | 用 JSON 手动指定角色模型，见下节 |
| `--global-instructions` | 把全局协作规则合并进现有 `AGENTS.md` 的托管区，未指定则不动全局文件 |
| `--replace-existing` | 授权覆盖已存在且内容不同的角色文件；不加就拒绝覆盖 |
| `--list-models` | 只列出本机 provider 和模型引用 |

## 步骤三：按需改模型

如果你这台电脑没有 Astra、Luna 或 K3，或者想换别的模型，用路由文件显式指定，不要让安装器猜。

`routes.json`：

```json
{
  "architect":         { "model": "custom:<providerId>:<modelId>", "thoughtLevel": "xhigh" },
  "builder":           { "model": "custom:<providerId>:<modelId>", "thoughtLevel": "xhigh" },
  "verifier":          { "model": "custom:<providerId>:<modelId>", "thoughtLevel": "max" },
  "reviewer":          { "model": "custom:<providerId>:<modelId>", "thoughtLevel": "max" },
  "expert":            { "model": "custom:<providerId>:<modelId>", "thoughtLevel": "xhigh" },
  "reviewer-fallback": { "model": "custom:<providerId>:<modelId>", "thoughtLevel": "xhigh" },
  "Explore":           { "model": "custom:<providerId>:<modelId>", "thoughtLevel": "max" },
  "general-purpose":   { "model": "custom:<providerId>:<modelId>", "thoughtLevel": "max" }
}
```

```bash
python3 scripts/install.py --routes routes.json
python3 scripts/install.py --routes routes.json --apply
```

可以只覆盖部分角色，其余角色仍走自动检测。模型名存在多个 provider 时安装器会报错让你选，而不是随便挑一个——`custom:providerId:modelId` 写错会静默走到别的服务，这比报错危险得多。

## 全局协作规则

`global/AGENTS.md` 是给**主会话**用的全局协作规则，不是子智能体提示词。它以英文写成，针对 GPT-6 Astra 的已知行为做了优化。要合并到本机全局配置：

```bash
python3 scripts/install.py --global-instructions --apply
```

规则会被放在托管标记之间：

```
<!-- zcode-subagents:begin -->
...
<!-- zcode-subagents:end -->
```

托管区之外的原有内容保持不变，重复执行结果相同。如果标记缺失或出现多组，安装器会停止而不是猜。

`~/.zcode/AGENTS.md` 里只放跨项目偏好。项目自己的架构、构建命令、领域规则写在项目的 `AGENTS.md`，它会在全局规则之后加载，可以收窄全局设置。

## 步骤四：验证真的生效

**文件写好了不等于生效。**按顺序确认：

1. **角色是否被加载**：新建一个 ZCode 会话，让它调用 `verifier`。如果返回 `Agent type 'verifier' not found`，说明当前进程还没加载新角色。自定义角色在启动时读取一次，**不会热加载**，需要新会话或重启 ZCode。
2. **实际用了哪个模型**：在本机运行记录里核对，不要相信角色的自我说明。运行记录会写请求实际使用的 provider、模型和推理参数。
3. **只读是否真的受限**：工具白名单和明确的行为约束能挡住大部分误操作，但它不是操作系统级沙箱。需要硬隔离时依靠宿主权限机制（见「已知限制」）。

如果发现模型没换、档位没生效，检查顺序：角色文件是否被加载 → `agents-state.json` 的覆盖是否写入 → 该模型在本机是否真的有这个档位。

## GPT-6 Astra 的提示词要点

这份全局规则和角色提示词参考了 OpenAI 官方对 GPT-6 Astra 的说明，针对它的几个已知倾向做了处理：

- **它会过多提问**：初稿中它在意图不完全明确时倾向停下来问。规则里明确「请求隐含行动时就是执行指令」，把澄清限制在「答案会改变结果」的问题上。
- **它对指令文件更敏感**：Astra 更容易被 `AGENTS.md` 和技能文件里的说明影响，冲突的指引会让它提前停下。所以规则里固定了优先级：**用户指令 > 本文件 > 项目 AGENTS.md > 技能**，并要求在停顿前说出是哪条规则导致的。
- **它可能不爱派发子智能体**：需要明确告诉它何时该并行派发，以及派发时要说清楚什么。
- **它偏长、偏格式化**：容易堆列表和表格，跨会话重复同样的措辞，因此规则里要求按需选择篇幅与格式、不要默认列表。
- **它对小任务可能验证过度**：规则里要求按变更风险选择验证范围，不机械跑全量测试。
- **子智能体角色由运行时注入**：所以全局规则里**不再重复角色和路由表**，避免和运行时注入的说明互相冲突。

来源：OpenAI 官方文档（`developers.openai.com`）的 GPT-6 Astra 模型指南与提示工程指南。模型本身的推理档位支持 `low`、`medium`、`high`、`xhigh`、`max`。

## 关于只读角色的 MCP 检索工具

`architect`、`reviewer`、`reviewer-fallback` 的 `tools` 白名单里包含四个 `mcp__codegraph__*` 条目。

它们是**可选的**：只在你本机配置了 `codegraph` 这个 MCP server 时才可用。没有配置时这些名字匹配不到任何工具，会被静默忽略，**不会导致角色加载失败或报错**。

如果不需要，直接从对应角色的 `tools` 列表里删掉这四行即可。安装器不会因为缺少 codegraph 而拒绝安装。

## 已知限制

- **不是热加载**：改完角色文件必须新建会话或重启，否则当前会话看不到新角色。
- **只读不是沙箱**：`architect`、`reviewer`、`reviewer-fallback` 用工具白名单加明确约束来限制写入，但都保留了 `Bash` 用于检索。真正的隔离要靠宿主权限机制。
- **`providerId` 不能跨机器复制**：每台电脑的 provider UUID 不同，必须用本机 `--list-models` 的结果生成 `MODEL_REF`。
- **中转站模型名不等于官方直连**：`custom:<providerId>:gpt-6-astra` 只说明本机向哪个服务发送了哪个模型名，不代表上游实现、配额或计算预算。需要真实确保模型时，从运行记录核对。
- **推理档位需要真实参数映射**：在 ZCode 里给模型列出某个档位，不保证请求里真的带上了对应参数。部分模型需要用应用支持的推理配置档案才能生成实际参数。安装后按「步骤四」核对。
- **`reviewer-fallback` 不是自动降级**：ZCode 没有配置跨角色的模型自动 fallback。主审查模型失败时，需要主会话显式调用这个角色并说明原因。

## 卸载与回滚

- 角色文件：删除 `~/.zcode/agents/` 下对应的六个 `.md`。
- 内置覆盖：编辑 `~/.zcode/v2/agents-state.json`，移除 `builtInModelOverrides`、`builtInThoughtLevelOverrides` 中的 `Explore`、`general-purpose`。
- 全局规则：删除 `<!-- zcode-subagents:begin -->` 与 `<!-- zcode-subagents:end -->` 之间的内容。
- 安装器每次写入前都在 `~/.zcode/backups/` 留下带时间戳的备份，可直接取回原文件。

改动配置前先备份，改完确认加载，再用一次真实调用确认生效——保存成功不等于已经起作用。
