#!/usr/bin/env python3
"""把一个 ZCode 子智能体配置包安装到本机。

默认只预演（dry-run），加 --apply 才会写入。只使用 Python 标准库。

设计原则：
- 只读现有配置来解析模型，绝不修改 v2/config.json，绝不写入或回显任何凭据。
- 所有预检通过后才开始写入；任何一步失败都不留下半成品。
- 只在 agents-state.json 中合并内置角色的模型与档位覆盖，保留其他字段。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_PLACEHOLDER = "{{MODEL_REF}}"
LEVEL_PLACEHOLDER = "{{THOUGHT_LEVEL}}"
BEGIN_MARK = "<!-- zcode-subagents:begin -->"
END_MARK = "<!-- zcode-subagents:end -->"
BUILT_IN_ROLES = ("Explore", "general-purpose")

# role -> (model id, reasoning level)
DEFAULT_ROUTES: dict[str, tuple[str, str]] = {
    "Explore": ("gpt-5.6-luna", "max"),
    "general-purpose": ("gpt-5.6-luna", "max"),
    "architect": ("gpt-6-astra", "xhigh"),
    "builder": ("gpt-6-astra", "xhigh"),
    "expert": ("gpt-6-astra", "xhigh"),
    "reviewer-fallback": ("gpt-6-astra", "xhigh"),
    "verifier": ("gpt-5.6-luna", "max"),
    "reviewer": ("k3", "max"),
}

PROTECTED_NAME = "config.json"


class InstallError(RuntimeError):
    """预检或写入失败。调用方不应继续任何写入。"""


@dataclass
class Plan:
    """一次安装的完整结果。apply 之前不做任何写入。"""

    writes: dict[Path, str] = field(default_factory=dict)
    state_path: Path | None = None
    state_before: dict | None = None
    state_after: dict | None = None
    backups: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    routes_used: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.writes and self.state_after == self.state_before


def read_json(path: Path, *, required: bool = True) -> dict:
    if not path.is_file():
        if required:
            raise InstallError(f"缺少必需文件：{path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InstallError(f"{path} 不是合法 JSON：{exc}") from exc


def load_providers(config_path: Path) -> dict:
    config = read_json(config_path)
    providers = config.get("provider")
    if not isinstance(providers, dict):
        raise InstallError(f"{config_path} 中没有 provider 配置")
    return providers


def usable_models(providers: dict) -> dict[str, list[tuple[str, str]]]:
    """model id -> [(providerId, providerName)]，只统计真正可用的 provider。"""
    index: dict[str, list[tuple[str, str]]] = {}
    for provider_id, provider in providers.items():
        if not isinstance(provider, dict):
            continue
        if provider.get("enabled") is False or provider.get("systemDisabledReason"):
            continue
        models = provider.get("models")
        if not isinstance(models, dict):
            continue
        name = provider.get("name") or provider_id
        for model_id in models:
            index.setdefault(model_id, []).append((provider_id, name))
    return index


def resolve_model_ref(index: dict, model_id: str) -> str:
    """把模型 ID 解析成本机的 custom:<providerId>:<modelId>，歧义或缺失即失败。"""
    matches = index.get(model_id)
    if not matches:
        raise InstallError(
            f"本机没有已启用且可用的模型「{model_id}」。"
            "请先在 ZCode 的 Settings → Models 中添加，或用 --routes 手动指定。"
        )
    if len(matches) > 1:
        listing = "、".join(f"{name} ({pid})" for pid, name in matches)
        raise InstallError(
            f"模型「{model_id}」在多个 provider 中都存在：{listing}。"
            "请用 --routes 显式指定 custom:<providerId>:<modelId>，不要让它自动挑选。"
        )
    provider_id, _ = matches[0]
    return f"custom:{provider_id}:{model_id}"


def load_routes(routes_path: Path | None) -> dict:
    if routes_path is None:
        return {}
    data = read_json(routes_path)
    if not isinstance(data, dict):
        raise InstallError(f"{routes_path} 必须是 JSON 对象")
    routes = {}
    for role, spec in data.items():
        if not isinstance(spec, dict) or "model" not in spec:
            raise InstallError(f"{routes_path} 中角色「{role}」必须给出 model 字段")
        routes[role] = {
            "model": str(spec["model"]),
            "thoughtLevel": str(spec.get("thoughtLevel", "")),
        }
    return routes


def build_routes(providers: dict, overrides: dict) -> dict[str, dict[str, str]]:
    """合并默认路由与用户覆盖，解析出每个角色的最终模型引用。"""
    index = usable_models(providers)
    resolved: dict[str, dict[str, str]] = {}
    for role, (model_id, level) in DEFAULT_ROUTES.items():
        override = overrides.get(role)
        if override is not None:
            ref = override["model"]
            if not ref.startswith("custom:") or ref.count(":") < 2:
                raise InstallError(
                    f"角色「{role}」的 model 必须是 custom:<providerId>:<modelId>，收到：{ref}"
                )
            resolved[role] = {"model": ref, "thoughtLevel": override["thoughtLevel"] or level}
        else:
            resolved[role] = {"model": resolve_model_ref(index, model_id), "thoughtLevel": level}
    for role, spec in overrides.items():
        if role not in resolved:
            resolved[role] = dict(spec)
    return resolved


def render_role(template: str, role: str, ref: str, level: str) -> str:
    if MODEL_PLACEHOLDER not in template:
        raise InstallError(f"角色「{role}」的模板缺少 {MODEL_PLACEHOLDER} 占位符")
    if LEVEL_PLACEHOLDER not in template:
        raise InstallError(f"角色「{role}」的模板缺少 {LEVEL_PLACEHOLDER} 占位符")
    if not level:
        raise InstallError(f"角色「{role}」没有可用档位")
    # 模板里的档位占位符带引号以便模板自身是合法 YAML；输出按 ZCode 的写法去掉引号。
    rendered = template.replace(MODEL_PLACEHOLDER, ref)
    rendered = rendered.replace(f'"{LEVEL_PLACEHOLDER}"', level).replace(LEVEL_PLACEHOLDER, level)
    if MODEL_PLACEHOLDER in rendered or LEVEL_PLACEHOLDER in rendered:
        raise InstallError(f"角色「{role}」渲染后仍残留占位符")
    if f'name: "{role}"' not in rendered:
        raise InstallError(f"角色「{role}」的模板 frontmatter 名称不匹配")
    return rendered


def merge_global(existing: str, block: str) -> str:
    """把全局规则写进托管标记之间，保留标记之外的内容。重复执行结果相同。"""
    has_begin = BEGIN_MARK in existing
    has_end = END_MARK in existing
    if has_begin != has_end:
        raise InstallError("现有 AGENTS.md 只有单侧托管标记，无法安全合并；请先手动修复")
    if existing.count(BEGIN_MARK) > 1 or existing.count(END_MARK) > 1:
        raise InstallError("现有 AGENTS.md 出现多组托管标记，请先手动清理")
    section = f"{BEGIN_MARK}\n{block.strip()}\n{END_MARK}\n"
    if not has_begin:
        head = existing.rstrip("\n")
        return f"{head}\n\n{section}" if head else section
    head, _, rest = existing.partition(BEGIN_MARK)
    _, _, tail = rest.partition(END_MARK)
    tail = tail.lstrip("\n")
    return f"{head}{section}\n{tail}" if tail else f"{head}{section}"


def merge_state(state: dict, routes: dict[str, dict[str, str]]) -> dict:
    merged = json.loads(json.dumps(state))
    models = dict(merged.get("builtInModelOverrides") or {})
    levels = dict(merged.get("builtInThoughtLevelOverrides") or {})
    for role in BUILT_IN_ROLES:
        if role in routes:
            models[role] = routes[role]["model"]
            levels[role] = routes[role]["thoughtLevel"]
    merged["builtInModelOverrides"] = models
    merged["builtInThoughtLevelOverrides"] = levels
    return merged


def build_plan(
    repo: Path,
    zcode_home: Path,
    *,
    routes_path: Path | None = None,
    replace_existing: bool = False,
    global_instructions: bool = False,
) -> Plan:
    """执行全部预检并返回计划；不写入任何文件。"""
    plan = Plan()
    agents_src = repo / "agents"
    if not agents_src.is_dir():
        raise InstallError(f"找不到角色模板目录：{agents_src}")

    providers = load_providers(zcode_home / "v2" / "config.json")
    routes = build_routes(providers, load_routes(routes_path))
    plan.routes_used = routes

    state_path = zcode_home / "v2" / "agents-state.json"
    state = read_json(state_path, required=False)
    disabled = state.get("disabledAgentIds") or []
    if not isinstance(disabled, list):
        raise InstallError(f"{state_path} 的 disabledAgentIds 不是数组")

    agents_dest = zcode_home / "agents"
    for role in DEFAULT_ROUTES:
        if role in BUILT_IN_ROLES:
            continue
        if f"user:user:{role}" in disabled:
            raise InstallError(
                f"角色「{role}」在 agents-state.json 的 disabledAgentIds 中被停用。"
                "请先在 ZCode 的 Settings → Subagents 中启用它，安装器不会替你删除停用意图。"
            )
        template_path = agents_src / f"{role}.md"
        if not template_path.is_file():
            raise InstallError(f"缺少角色模板：{template_path}")
        content = render_role(
            template_path.read_text(encoding="utf-8"),
            role,
            routes[role]["model"],
            routes[role]["thoughtLevel"],
        )
        dest = agents_dest / f"{role}.md"
        if dest.is_file():
            if dest.read_text(encoding="utf-8") == content:
                plan.notes.append(f"{role}: 内容一致，无需改动")
                continue
            if not replace_existing:
                raise InstallError(
                    f"{dest} 已存在且内容不同。确认要覆盖请加 --replace-existing。"
                )
        plan.writes[dest] = content

    if global_instructions:
        template = (repo / "global" / "AGENTS.md")
        if not template.is_file():
            raise InstallError(f"缺少全局规则模板：{template}")
        target = zcode_home / "AGENTS.md"
        existing = target.read_text(encoding="utf-8") if target.is_file() else ""
        merged = merge_global(existing, template.read_text(encoding="utf-8"))
        if merged != existing:
            plan.writes[target] = merged
        else:
            plan.notes.append("AGENTS.md: 托管区内容一致，无需改动")

    merged_state = merge_state(state, routes)
    if merged_state != state:
        plan.state_path = state_path
        plan.state_before = state
        plan.state_after = merged_state
    else:
        plan.notes.append("agents-state.json: 内容一致，无需改动")
    return plan


def ensure_backup(plan: Plan, zcode_home: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = zcode_home / "backups" / f"zcode-subagents-{stamp}"
    suffix = 1
    while backup_dir.exists():
        backup_dir = zcode_home / "backups" / f"zcode-subagents-{stamp}-{suffix}"
        suffix += 1
    backup_dir.mkdir(parents=True, exist_ok=False)
    os.chmod(backup_dir, 0o700)
    targets = list(plan.writes)
    if plan.state_path is not None:
        targets.append(plan.state_path)
    for target in targets:
        if target.is_file():
            relative = target.relative_to(zcode_home)
            dest = backup_dir / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, dest)
            os.chmod(dest, 0o600)
            plan.backups.append(dest)
    return backup_dir


def atomic_write(path: Path, content: str, baseline: str | None) -> None:
    """先核对读取基线，再原子替换，避免覆盖并发修改。"""
    if baseline is not None:
        if not path.is_file():
            raise InstallError(f"{path} 在写入前消失，已中止")
        if path.read_text(encoding="utf-8") != baseline:
            raise InstallError(f"{path} 在计划生成后被改动，已中止以免覆盖")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def apply_plan(plan: Plan, zcode_home: Path) -> Path:
    if plan.is_empty:
        return Path()
    baseline = {
        path: (path.read_text(encoding="utf-8") if path.is_file() else None)
        for path in plan.writes
    }
    state_baseline = None
    if plan.state_path is not None:
        state_baseline = (
            plan.state_path.read_text(encoding="utf-8") if plan.state_path.is_file() else None
        )
    backup_dir = ensure_backup(plan, zcode_home)
    for path, content in plan.writes.items():
        atomic_write(path, content, baseline[path])
    if plan.state_path is not None and plan.state_after is not None:
        atomic_write(
            plan.state_path,
            json.dumps(plan.state_after, ensure_ascii=False, indent=2) + "\n",
            state_baseline,
        )
    return backup_dir


def describe_plan(plan: Plan) -> str:
    lines = ["将执行以下改动：" if not plan.is_empty else "没有需要改动的内容。"]
    for path in sorted(plan.writes):
        action = "更新" if path.is_file() else "新建"
        lines.append(f"  {action} {path}")
    if plan.state_path is not None:
        lines.append(f"  合并 {plan.state_path}（保留其他字段与停用列表）")
    for role, spec in plan.routes_used.items():
        lines.append(f"  路由 {role} -> {spec['model']} @ {spec['thoughtLevel']}")
    lines.extend(f"  说明 {note}" for note in plan.notes)
    lines.append("不会修改 v2/config.json，不会写入凭据，不会修改主会话模型。")
    return "\n".join(lines)


def cmd_list_models(zcode_home: Path) -> int:
    providers = load_providers(zcode_home / "v2" / "config.json")
    index = usable_models(providers)
    if not index:
        print("没有找到已启用且可用的模型。")
        return 1
    by_provider: dict[str, list[str]] = {}
    for model_id, matches in index.items():
        for provider_id, name in matches:
            by_provider.setdefault(f"{name}  ({provider_id})", []).append(model_id)
    for label in sorted(by_provider):
        print(f"provider  {label}")
        for model_id in sorted(by_provider[label]):
            provider_id = label.rsplit("(", 1)[1].rstrip(")")
            print(f"  custom:{provider_id}:{model_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="安装 ZCode 子智能体角色文件与内置角色覆盖（默认预演）"
    )
    parser.add_argument("--apply", action="store_true", help="实际写入；不加则只预演")
    parser.add_argument("--zcode-home", default="~/.zcode", help="目标 ZCode 目录，默认 ~/.zcode")
    parser.add_argument("--repo", default=str(REPO_ROOT), help="本配置包目录，默认自动定位")
    parser.add_argument("--routes", default=None, help="JSON 路由文件，覆盖默认模型")
    parser.add_argument("--global-instructions", action="store_true", help="合并全局协作规则")
    parser.add_argument("--replace-existing", action="store_true", help="授权覆盖不同的同名角色文件")
    parser.add_argument("--list-models", action="store_true", help="只列出本机可用模型引用")
    args = parser.parse_args(argv)

    zcode_home = Path(args.zcode_home).expanduser().resolve()
    if args.list_models:
        try:
            return cmd_list_models(zcode_home)
        except InstallError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2

    try:
        plan = build_plan(
            Path(args.repo).expanduser().resolve(),
            zcode_home,
            routes_path=Path(args.routes).expanduser().resolve() if args.routes else None,
            replace_existing=args.replace_existing,
            global_instructions=args.global_instructions,
        )
    except InstallError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        print("未写入任何文件。", file=sys.stderr)
        return 2

    print(describe_plan(plan))
    if not args.apply:
        print("\n预演结束。确认无误后加 --apply 写入。")
        return 0
    if plan.is_empty:
        print("\n无需写入。")
        return 0
    try:
        backup_dir = apply_plan(plan, zcode_home)
    except InstallError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    print(f"\n已写入。备份：{backup_dir}")
    print("自定义角色需要新建会话或重启 ZCode 后才会加载。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
