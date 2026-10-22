"""只读校验共享讨论、等待完整交接；不判断论据真假或代写发言。"""
from __future__ import annotations
import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import sys
import time


class Invalid(ValueError):
    pass


class Incomplete(ValueError):
    pass


@dataclass
class Result:
    kind: str
    message: str
    protected_end: int = 0


def mask_fences(text: str) -> str:
    """代码示例不参与协议解析；保留字符位置。"""
    fence = None
    result = []
    for line in text.splitlines(keepends=True):
        match = re.match(r"^\s{0,3}([" + chr(96) + r"~]{3,})(.*)$", line)
        was_inside = fence is not None
        if match and len(set(match[1])) == 1:
            if fence is None:
                fence = (match[1][0], len(match[1]))
            elif (match[1][0] == fence[0] and len(match[1]) >= fence[1]
                  and not match[2].strip()):
                fence = None
        if was_inside or fence is not None or match:
            result.append("".join("\n" if c == "\n" else " " for c in line))
        else:
            result.append(line)
    return "".join(result)


def single(text: str, pattern: str, label: str) -> str:
    matches = re.findall(pattern, text, re.M)
    if len(matches) > 1:
        raise Invalid(f"{label}重复")
    if not matches:
        raise Incomplete(f"等待{label}")
    return matches[0]


def field(section: str, name: str) -> str:
    values = re.findall(r"^\| " + re.escape(name) + r" \| ([^\n]*) \|$", section, re.M)
    if len(values) != 1:
        raise Invalid(f"署名字段“{name}”须恰好一项")
    return values[0].strip()


def only_separators(text: str) -> bool:
    return all(line.strip() in ("", "---") for line in text.splitlines())


def initial_prefix(text: str) -> bytes:
    markers = list(re.finditer(r"^<!-- TURN_DONE:[0-9]+:[A-Z] -->\n?", mask_fences(text), re.M))
    return text[:markers[-1].end()].encode("utf-8") if markers else b""


def inspect_document(text: str, target: int, expected_next: str) -> Result:
    masked = mask_fences(text)
    protocol = single(masked, r"^<!-- DISCUSSION_PROTOCOL:([^\n]+) -->$", "协议版本")
    if protocol != "2":
        raise Invalid("本脚本要求协议2；旧记录应按原协议处理，不自动重写")
    roles = single(masked, r"^<!-- DISCUSSION_ROLES:([A-Z](?:,[A-Z])*) -->$", "角色表").split(",")
    if len(roles) < 2 or roles[0] != "A" or len(set(roles)) != len(roles):
        raise Invalid("角色表须以A开始、至少两方且无重复")
    planned = int(single(masked, r"^<!-- DISCUSSION_CHALLENGE_ROUNDS:([0-9]+) -->$", "计划对峙轮数"))
    if planned < 1:
        raise Invalid("计划对峙轮数须为正整数")
    summarizer = single(masked, r"^<!-- DISCUSSION_SUMMARIZER:([A-Z]) -->$", "汇总人")
    if summarizer not in roles:
        raise Invalid("汇总人必须属于参与方")
    if roles[target % len(roles)] != expected_next:
        raise Invalid("目标轮次与预期下一角色不匹配")
    eof = single(masked, r"^(<!-- DISCUSSION_EOF -->)$", "EOF哨兵")
    if not masked.rstrip().endswith(eof):
        raise Incomplete("等待EOF恢复到文末")
    eof_start = masked.rfind(eof)
    headings = list(re.finditer(r"^## 第 ([0-9]+) 轮 · ([A-Z])方$", masked, re.M))
    if not headings:
        raise Incomplete("等待首轮发言")
    done = {}
    for marker in re.finditer(r"^<!-- TURN_DONE:([^\n]*) -->$", masked, re.M):
        match = re.fullmatch(r"([0-9]+):([A-Z])", marker[1])
        if not match:
            raise Invalid("完成标记格式错误")
        key = (int(match[1]), match[2])
        if key in done:
            raise Invalid(f"完成标记重复：{marker[0]}")
        if key[0] < 1 or key[0] > len(headings) or roles[(key[0]-1) % len(roles)] != key[1]:
            raise Invalid(f"完成标记无对应轮次/角色：{marker[0]}")
        done[key] = marker
    summaries = list(re.finditer(r"^## 最终方案汇总 · ([A-Z])方$", masked, re.M))
    closures = list(re.finditer(r"^<!-- DISCUSSION_CLOSED:F([0-9]+):([A-Z]) -->$", masked, re.M))
    if len(summaries) > 1 or len(closures) > 1:
        raise Invalid("结案汇总或结案标记重复")
    summary = summaries[0] if summaries else None
    if summary and summary.start() < headings[-1].start():
        raise Invalid("结案汇总后不能再有编号发言")
    if closures and not summary:
        raise Invalid("结案标记缺少汇总正文")

    bg_version, previous_phase = None, None
    bg_accept, final_accept = {}, {}
    completed_cycles, cycle_members = 0, set()
    required_cycles, extended = planned, False
    latest_final, active_final = 0, None
    protected_end, pending = 0, False

    for index, heading in enumerate(headings):
        turn, role = int(heading[1]), heading[2]
        if turn != index+1 or role != roles[index % len(roles)]:
            raise Invalid(f"第{index+1}个标题的轮次或角色越序")
        end = headings[index+1].start() if index+1 < len(headings) else (summary.start() if summary else eof_start)
        marker = done.get((turn, role))
        if marker is None:
            if index+1 < len(headings) or summary:
                raise Invalid(f"历史第{turn}轮缺完成标记，后续内容却已开始")
            pending = True
            break
        if not heading.end() < marker.start() < end:
            raise Invalid(f"第{turn}轮完成标记不在本轮内")
        if not only_separators(masked[marker.end():end]):
            raise Invalid(f"第{turn}轮完成标记后仍有正文")
        protected_end = marker.end() + int(text[marker.end():].startswith("\n"))
        section = masked[heading.end():marker.start()]
        if not re.search(r"^> 发言人：" + role + r"方[^\n]+$", section, re.M):
            raise Invalid(f"第{turn}轮缺少身份行")
        if not field(section, "发言人").startswith(role+"方"):
            raise Invalid(f"第{turn}轮署名角色不匹配")
        if field(section, "立场") not in ("未接受", "有条件接受", "接受"):
            raise Invalid(f"第{turn}轮立场无效")
        try:
            stage = single(section, r"^阶段：([^\n]+)$", "阶段标签")
        except Incomplete as exc:
            raise Invalid(f"已完成的第{turn}轮缺阶段标签") from exc
        if stage == "背景共识":
            phase, cycle = "background", None
        elif match := re.fullmatch(r"对峙第\s*([1-9][0-9]*)\s*轮", stage):
            phase, cycle = "challenge", int(match[1])
        elif re.fullmatch(r"理性解决(?:第\s*[1-9][0-9]*\s*轮)?", stage):
            phase, cycle = "resolve", None
        else:
            raise Invalid(f"第{turn}轮阶段标签无效")
        background = re.fullmatch(r"v([0-9]+)[，,]\s*(接受|待修订)", field(section, "背景基准"))
        if not background:
            raise Invalid(f"第{turn}轮背景版本/状态无效")
        version, acceptance = int(background[1]), background[2]
        final_value, unresolved = field(section, "最终方案"), field(section, "未决问题")
        if not unresolved:
            raise Invalid("未决问题须为0或明确问题编号")
        definitions = re.findall(r"^### 最终方案 F([0-9]+)$", section, re.M)
        if phase != "resolve" and (definitions or final_value != "无"):
            raise Invalid("最终方案只能在理性解决阶段发表或签署")
        if phase == "background":
            if bg_version is None and version != 0:
                raise Invalid("背景首版须为v0")
            if bg_version is not None and (version < bg_version or version > bg_version+1):
                raise Invalid("背景版本必须保留当前版或递增一版")
            if previous_phase not in (None, "background") and version == bg_version:
                raise Invalid("返回背景阶段须追加新基准，不能沿用旧签署")
            if version != bg_version:
                bg_accept.clear()
                active_final = None
                final_accept.clear()
                completed_cycles, cycle_members = 0, set()
                required_cycles, extended = planned, False
            bg_version = version
            bg_accept[role] = acceptance
        else:
            if version != bg_version or any(bg_accept.get(r) != "接受" for r in roles):
                raise Invalid("全体尚未接受同一背景基准，不能进入对峙/解决阶段")
            if acceptance != "接受":
                raise Invalid("撤回背景接受时应返回背景阶段修订")
            if phase == "challenge":
                expected_cycle = completed_cycles+1
                if cycle != expected_cycle:
                    raise Invalid(f"对峙应为第{expected_cycle}轮，不能跳轮或重复已完成轮次")
                if cycle > required_cycles:
                    reason = re.search(r"^追加对峙原因：(.+)$", section, re.M)
                    if extended or cycle != required_cycles+1 or not reason or not reason[1].strip():
                        raise Invalid("额外对峙仅可追加一次，并写明追加对峙原因")
                    required_cycles += 1
                    extended = True
                if previous_phase == "resolve" and cycle <= planned:
                    raise Invalid("解决阶段不能退回已完成的对峙轮")
                if previous_phase == "resolve":
                    active_final = None
                    final_accept.clear()
                if role in cycle_members:
                    raise Invalid("同一对峙轮中角色重复")
                cycle_members.add(role)
                if len(cycle_members) == len(roles):
                    completed_cycles += 1
                    cycle_members.clear()
            else:
                if completed_cycles < required_cycles or cycle_members:
                    raise Invalid("计划对峙轮次尚未由全体完成，不能开始理性解决")
                if len(definitions) > 1:
                    raise Invalid("一个发言只能发表一个最终方案版本")
                if definitions:
                    new_final = int(definitions[0])
                    if new_final != latest_final+1:
                        raise Invalid("最终方案须从F1递增，不重用或跳过版本")
                    latest_final = active_final = new_final
                    final_accept.clear()
                if final_value != "无":
                    signed = re.fullmatch(r"F([0-9]+)[，,]\s*(未接受|有条件接受|接受)", final_value)
                    if not signed or active_final is None or int(signed[1]) != active_final:
                        raise Invalid("署名必须引用已发表的当前最终方案版本")
                    if signed[2] == "接受" and unresolved != "0":
                        raise Invalid("最终接受时仍有未决问题，不能签署为接受")
                    final_accept[role] = signed[2]
                elif active_final is not None:
                    raise Invalid("当前方案已发表，须明确对该版本的立场")
        previous_phase = phase

    consensus = active_final is not None and all(final_accept.get(r) == "接受" for r in roles)
    if summary:
        if pending or not consensus or previous_phase != "resolve":
            raise Invalid("尚未全体签署当前方案，不能开始结案汇总")
        if summary[1] != summarizer:
            raise Invalid("结案汇总人不是初始化时指定的角色")
        if not closures:
            return Result("WAIT", "等待指定汇总人完成汇总", protected_end)
        closure = closures[0]
        if int(closure[1]) != active_final or closure[2] != summarizer or closure.start() < summary.end():
            raise Invalid("结案标记的版本、角色或位置不匹配")
        body = masked[summary.end():closure.start()]
        if not re.search(r"^> 汇总人："+summarizer+r"方[^\n]+$", body, re.M):
            raise Invalid("结案汇总缺少汇总人身份行")
        if not re.search(r"^最终方案版本：F"+str(active_final)+r"$", body, re.M):
            raise Invalid("结案汇总缺少当前方案版本")
        if masked[closure.end():eof_start].strip():
            raise Invalid("结案标记后只能保留EOF")
        return Result("DISCUSSION_CLOSED", f"final=F{active_final} summarizer={summarizer}", protected_end)
    if pending:
        return Result("WAIT", "等待当前轮完成标记", protected_end)
    if consensus:
        return Result("SUMMARY_READY", f"final=F{active_final} summarizer={summarizer}", protected_end)
    latest = len(headings)
    if latest < target:
        return Result("WAIT", f"等待第{target}轮", protected_end)
    if latest > target:
        return Result("STALE_TARGET", f"latest_turn={latest} next_role={roles[latest % len(roles)]}", protected_end)
    return Result("TURN_READY", f"completed_turn={target} next_role={expected_next}", protected_end)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("completed_turn", type=int)
    parser.add_argument("expected_next")
    parser.add_argument("timeout", type=float, nargs="?", default=0)
    parser.add_argument("--poll-seconds", type=float, default=2)
    parser.add_argument("--stable-seconds", type=float, default=4)
    args = parser.parse_args()
    if (args.completed_turn < 1 or not re.fullmatch("[A-Z]", args.expected_next)
            or args.timeout < 0 or args.poll_seconds <= 0 or args.stable_seconds <= 0):
        parser.error("轮次、角色、超时或轮询参数无效")
    try:
        initial = args.file.read_bytes()
        protected = initial_prefix(initial.decode("utf-8"))
    except (OSError, UnicodeError) as exc:
        print(f"错误：无法读取讨论文件：{exc}", file=sys.stderr)
        return 2
    started = stable_since = time.monotonic()
    last_digest, reported = None, None
    while True:
        now = time.monotonic()
        try:
            data = args.file.read_bytes()
            digest = hashlib.sha256(data).digest()
            if digest != last_digest:
                last_digest, stable_since = digest, now
            if now-stable_since >= args.stable_seconds:
                if protected and not data.startswith(protected):
                    raise Invalid("监测开始以来已完成的历史内容被改写或截断")
                text = data.decode("utf-8")
                state = inspect_document(text, args.completed_turn, args.expected_next)
                if state.protected_end:
                    protected = text[:state.protected_end].encode("utf-8")
                if state.kind != "WAIT":
                    print(f"{state.kind} {state.message}")
                    return 5 if state.kind == "STALE_TARGET" else 0
                message = state.message
            else:
                message = "等待文件内容稳定"
        except Incomplete as exc:
            message = str(exc)
        except Invalid as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 3
        except (OSError, UnicodeError) as exc:
            message = f"等待文件恢复可读：{exc}"
        if message != reported:
            print(message, file=sys.stderr)
            reported = message
        if args.timeout and time.monotonic()-started >= args.timeout:
            print(f"WAIT_TIMEOUT file={args.file} completed_turn={args.completed_turn} next_role={args.expected_next}")
            return 4
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    sys.exit(main())
