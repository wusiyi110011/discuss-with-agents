# discuss-with-agents · 多代理协作讨论

用一份共享 Markdown，让真实子代理或不同模型先对齐背景，再进行三轮完整对峙、逐项解决问题，最后由指定参与方汇总。

适合方案评审、技术决策、观点比较与共同完善。所有发言来自实际运行的参与者；同模型多代理会如实标明，不冒充不同模型的独立验证。

## 工作方式

1. **背景共识**：区分事实、假设和未知，所有参与者接受同一背景版本后才推进。
2. **三轮对峙**：每轮全体各发言一次，依次检查证据、反例、执行和失败情形；此时登记问题，暂不答辩。
3. **理性解决**：逐项判断问题，记录处置、判据和责任，区分已解决、验证待办和已接受风险。
4. **指定方汇总**：全体签署同一最终方案且未决问题为零后结案；默认由 A 方汇总。

默认主代理 A 与一个真实子代理 B，复用参与者会话并严格轮流追加。也可接入用户指定的模型或现有参与者。共享账本保留完整历史，禁止代写他人发言、超时推定同意或篡改旧记录；无法收敛时交付分歧。

## 安装

把本仓库克隆到你的宿主所配置的技能目录，目录名保持 `discuss-with-agents`：

```bash
git clone https://github.com/wusiyi110011/discuss-with-agents.git /你的技能目录/discuss-with-agents
```

随后让支持 Agent Skills 的宿主加载根目录的 [SKILL.md](SKILL.md)。具体技能目录和加载方式以宿主配置为准；不要求固定的产品或用户目录。

手动使用时，也可将 `SKILL.md` 交给参与者阅读。需要一个可运行真实子代理的宿主，或至少两个已接入的真实参与者，并确保它们能访问同一个账本。没有参与者入口时，只交付背景草案和接入缺口，不模拟讨论。

## 使用示例

```text
使用 $discuss-with-agents，安排一个真实子代理与我方评审工作区中的缓存设计。
先核对背景，再完成三轮完整对峙，逐项处理问题，最后由 A 方汇总。
材料只在当前授权工作区内共享；这次只交付设计方案，不执行部署或实验。
```

完整讨论规范、角色交接格式和异常恢复见 [SKILL.md](SKILL.md)，账本模板见 [assets/discussion-template.md](assets/discussion-template.md)。

每场新建唯一账本；发言序号与完整对峙轮数分别计数。用户指定参与模型、角色、目录和汇总人时按指定执行。旧讨论不会被覆盖，验证计划也不会被写成已验证效果。

## 只读监测器

监测器使用 Python 标准库，无第三方 Python 依赖。需要 Python 3.10+；Shell 入口另需 Bash（Windows 可使用具备相同工具的环境）。

在仓库根目录运行，示例为等待 A 的第 1 个发言完成，普通下一角色为 B：

```bash
bash scripts/watch_discussion.sh /绝对路径/讨论主题.md 1 B 30
```

默认从 `PATH` 使用 `python3`。指定已有解释器：

```bash
DISCUSSION_PYTHON=/你的环境/bin/python bash scripts/watch_discussion.sh /绝对路径/讨论主题.md 1 B 30
```

也可直接运行 Python 入口：

```bash
python3 scripts/watch_discussion.py /绝对路径/讨论主题.md 1 B 30
```

`1` 是等待其完成的单个发言序号，`B` 是角色表中的普通下一角色，`30` 是监测超时秒数；超时 `0` 为无限监测，仅在真实参与者运行且宿主允许持续会话时使用。

| 退出码 | 含义与处理 |
|---|---|
| `0` | 查看输出：`TURN_READY` 为交接，`SUMMARY_READY` 为指定方汇总，`DISCUSSION_CLOSED` 为结案。 |
| `2` | 参数、解释器或启动读取失败；修正原因后重试。 |
| `3` | 协议损坏；停止写入并报告中断。 |
| `4` | `WAIT_TIMEOUT`：尚未观察到可继续状态，不代表同意。 |
| `5` | `STALE_TARGET`：目标发言已过，重读账本重新定位。 |

监测器校验协议 2 的标记、角色顺序、阶段、背景签署和方案版本，并保护监测开始以来已完成的历史前缀。它不能鉴别模型身份、判断论据真假或替代实质共识；两个接受字段的一致性仍需按技能逐项核对。

## 测试

在仓库根目录使用已有的 Python 解释器运行：

```bash
python3 -m unittest discover -s scripts -p 'test_watch_discussion.py' -v
```

测试覆盖模板交接、背景重签、完整轮次、条件接受、版本失效、指定汇总、半写入、历史篡改，以及 Shell 入口的解释器选择。GitHub Actions 对 Linux/macOS、Python 3.10/3.13 运行同一套测试。

[test-prompts.json](test-prompts.json) 提供三条行为验收场景及预期。做独立测试时，只向执行者提供 `prompt`，把 `expected` 留给评审者，避免泄漏验收答案。

## 仓库内容

| 路径 | 用途 |
|---|---|
| `SKILL.md` | 完整讨论流程与约束 |
| `agents/openai.yaml` | 支持该配置的宿主界面元数据 |
| `assets/discussion-template.md` | 唯一讨论账本模板 |
| `scripts/watch_discussion.py` | 只读协议校验与等待 |
| `scripts/watch_discussion.sh` | 可配置解释器的 Bash 入口 |
| `scripts/test_watch_discussion.py` | 标准库回归测试 |
| `test-prompts.json` | 行为验收场景 |

修改协议标记、阶段或签署规则时，同步检查技能、模板和解析器，并先运行测试。讨论内容与参与者权限由使用者管理，不把私有材料擅自交给外部模型。

## 许可证

本项目采用 [MIT License](LICENSE)。版权声明：2026 Siyu Wu（wusiyi110011）。
