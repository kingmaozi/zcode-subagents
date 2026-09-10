# GPT-6 Astra 提示词要点与来源

本仓库的全局规则 `global/AGENTS.md` 和六个角色的提示词针对 **GPT-6 Astra** 的已知行为做了调整。这份文档记录依据、来源和取舍，方便日后按模型更新维护。

来源：OpenAI 官方文档 `developers.openai.com`

- 模型指南：<https://developers.openai.com/api/docs/guides/latest-model>
- 模型页：<https://developers.openai.com/api/docs/models/gpt-6-astra>
- 提示工程：<https://developers.openai.com/api/docs/guides/prompt-engineering>
- 提示缓存：<https://developers.openai.com/api/docs/guides/prompt-caching>

## 模型事实

- 模型 ID 是 `gpt-6-astra`，官方定位为「最强端到端工作模型」，用于复杂推理、编码、电脑操作、调研和文档创作。
- 推理档位 `reasoning.effort` 支持 `low`、`medium`、`high`、`xhigh`、`max` —— 五档齐全。
- 官方称其输出 token 用量显著低于前代，因此「单任务预估 API 成本」可能更低，尽管单 token 价格更高。这意味着限制输出长度通常不是省钱的主要手段。
- 官方明确它「比 GPT-5.6 Sol 更智能」，同时有若干需要提示词配合的行为倾向。

## 五个需要注意的行为倾向

### 1. 主动性与追问

官方指出：Astra 更可能**在用户期望它自行假设并继续时停下来提问**。

官方的应对是让模型把「隐含请求」当成指令执行，原文示例（节选）：

> When the user's prompt indicates a request for action, such as "can you...", "I want to...", "help me..." and similar expressions, treat these as instructions to do the work and take action. Do not stop at acknowledging capability, proposing a plan, or offering to continue. Do not settle for a partial or "helpful enough" solution.

本仓库的处理：全局规则的「Default behavior」段落直接写入这条语义，并把澄清限制在「答案会改变结果」的问题上，同时要求**只问一次**。

### 2. 对指令文件更敏感

这是最容易踩坑的一条。官方原文：

> GPT-6 Astra is stronger at general instruction following than our previous models... It can be more sensitive to instructions contained in skills and other files, such as `AGENTS.md`. We **strongly recommend** auditing skills and other files accessible to your model for instructions that could influence its behavior.

同页还说：

> unclear or conflicting guidance in a skill file may cause the model to pause and block work early.

也就是说：**冲突或含糊的指令文件会让它提前停下、卡住工作**，而不是像前代那样忽略掉。

本仓库的两条应对：

1. **在全局文件里固定优先级**：用户指令 > 全局规则 > 项目 `AGENTS.md` > 技能文件。并要求它在停顿或改变方向前，说出是哪条规则导致的、引用原文、说明自己的理解。
2. **不在全局文件里重复子智能体角色表**。角色说明由 ZCode 运行时逐个注入到子智能体；在全局文件里再写一份会产生两处不一致的描述，恰好命中「冲突指令导致停摆」这一风险。这是本仓库刻意做出的取舍。

官方还给了一个用于排查静默冲突的提示词思路：让模型指出导致它暂停或偏离的技能名与具体规则，并区分「规则原文」和「它的解读」。这条已写进全局规则。

### 3. 个性与写作风格

官方：Astra **倾向于详细、格式化的回答**（列表、表格、Markdown），并且**可能跨会话重复使用同样的措辞**。

本仓库的处理：要求按请求选择篇幅与格式，不默认堆列表和表格，并明确要求避免跨会话重复相同的结尾话术。

### 4. 子智能体派发

官方：**它可能比你期望的更少派发子智能体**，需要明确说明何时、以多大力度使用子智能体。

本仓库的处理：全局规则里保留「Delegation」章节，说明何时该派发、派发时必须交代什么、并行写入时如何划分文件所有权。角色表本身交给运行时注入。

### 5. 测试与验证

官方：编码任务上它**倾向在认为任务完成前做充分测试**；对**小任务可能跑超出需要的测试**。

本仓库的处理：全局规则要求按变更风险选择验证范围，复用同一代码状态已有的验证，不机械跑全量测试。

## 提示缓存相关

官方文档提到，在 GPT-6 Astra 上可以通过追加 `configuration_update` 输入项在多次请求之间改变推理档位，同时保持请求级 `reasoning.effort` 不变，从而**保住原有前缀以便缓存复用**。

本仓库的处理：全局规则要求保持指令前缀稳定，把任务进度和日志放到会话末尾或项目文件，不要反复改写公共前缀。这与提示缓存的最佳实践一致，不只是为了省钱。

## 编码任务的官方建议

官方对 `gpt-6-astra` 的编码场景给出几条建议，与角色提示词的设计一致：

- **明确角色与工作流**：把模型定位成职责清晰的软件工程代理，说明何时不该用某个模式。
- **强制结构化工具使用**：给出示例，说明如何调用命令。
- **要求充分测试**：用单元测试或命令验证改动；注意类 `apply_patch` 的工具**即使失败也可能返回“Done”**，必须独立确认结果。
- **Markdown 规范**：使用内联代码、代码块、列表和表格，路径、函数、类名用反引号包裹。

前端场景官方推荐的技术栈：Tailwind CSS、shadcn/ui、Radix Themes；图标 Lucide、Material Symbols、Heroicons；动画 Motion。

> 注意：这条工具返回值不可信的建议是模型厂商对通用工具行为的提醒。若你使用的写入工具会返回成功但实际失败，验证必须以文件内容为准，而不是工具回执。

## 维护提示

- 模型行为会随版本变化。升级模型或换供应商后，重新核对上述五条是否仍然成立。
- 本机 ZCode 中若 `gpt-6-astra` 实际经由中转站提供，模型名相同不代表上游实现、配额或计算预算相同；需要确认真实模型时，从运行记录核对实际请求。
- 官方的「建议提示词」是英文原文，本仓库的全局规则以英文写成，便于与官方建议逐条对应；但角色产出统一要求用简体中文返回。
