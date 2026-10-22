"""协议行为回归检查；所有讨论均为临时测试夹具。"""
from pathlib import Path
import subprocess
import sys
import tempfile
import re
import os
import unittest

from watch_discussion import Invalid, inspect_document


class Document:
    def __init__(self, roles="AB", rounds=3, summarizer="A"):
        self.roles = roles
        self.parts = [f"<!-- DISCUSSION_PROTOCOL:2 -->\n<!-- DISCUSSION_ROLES:{','.join(roles)} -->\n"
                      f"<!-- DISCUSSION_CHALLENGE_ROUNDS:{rounds} -->\n<!-- DISCUSSION_SUMMARIZER:{summarizer} -->\n"]
        self.count = 0

    def turn(self, stage, background="v0，接受", final="无", define=None,
             unresolved="0", done=True, extra=""):
        self.count += 1
        role = self.roles[(self.count-1) % len(self.roles)]
        body = (f"## 第 {self.count} 轮 · {role}方\n阶段：{stage}\n"
                f"> 发言人：{role}方（测试夹具）\n事实：甲\n{extra}\n")
        if define:
            body += f"### 最终方案 F{define}\n测试方案内容\n"
        body += (f"| 发言人 | {role}方（测试夹具） |\n| 立场 | 未接受 |\n"
                 f"| 背景基准 | {background} |\n| 最终方案 | {final} |\n| 未决问题 | {unresolved} |\n")
        if done:
            body += f"<!-- TURN_DONE:{self.count}:{role} -->\n"
        self.parts.append(body+"\n")
        return self

    def prepare(self, rounds=3):
        for _ in self.roles:
            self.turn("背景共识")
        for cycle in range(1, rounds+1):
            for _ in self.roles:
                self.turn(f"对峙第 {cycle} 轮")
        return self

    def summary(self, role="A", version=1):
        self.parts.append(f"## 最终方案汇总 · {role}方\n> 汇总人：{role}方（测试夹具）\n"
                          f"最终方案版本：F{version}\n测试方案汇总\n"
                          f"<!-- DISCUSSION_CLOSED:F{version}:{role} -->\n")
        return self

    def text(self):
        return "".join(self.parts)+"<!-- DISCUSSION_EOF -->\n"

    def inspect(self):
        return inspect_document(self.text(), self.count, self.roles[self.count % len(self.roles)])


class ProtocolTests(unittest.TestCase):
    def test_filled_template_and_shell_entrypoint(self):
        template = Path(__file__).resolve().parents[1]/"assets/discussion-template.md"
        text = template.read_text()
        for old, new in (("{{未接受／有条件接受／接受}}", "未接受"),
                         ("{{接受/待修订}}", "接受"), ("{{0或问题编号}}", "0")):
            text = text.replace(old, new)
        text = re.sub(r"\{\{.*?\}\}", "测试夹具", text)
        self.assertEqual(inspect_document(text, 1, "B").kind, "TURN_READY")
        with tempfile.TemporaryDirectory(prefix="discussion-template-") as directory:
            path = Path(directory)/"discussion.md"
            path.write_text(text)
            skill_dir = Path(__file__).resolve().parents[1]
            wrapper = skill_dir/"scripts/watch_discussion.sh"
            result = subprocess.run(["bash", str(wrapper), str(path), "1", "B", "2",
                                     "--poll-seconds", "0.01", "--stable-seconds", "0.02"],
                                    env={**os.environ, "DISCUSSION_PYTHON": sys.executable},
                                    capture_output=True, text=True, timeout=4)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("TURN_READY", result.stdout)

    def test_shell_entrypoint_uses_python_from_path(self):
        with tempfile.TemporaryDirectory(prefix="discussion-python-path-") as directory:
            root = Path(directory)
            path = root/"discussion.md"
            path.write_text(Document().turn("背景共识").text())
            (root/"python3").symlink_to(sys.executable)
            env = {key: value for key, value in os.environ.items() if key != "DISCUSSION_PYTHON"}
            env["PATH"] = str(root)+os.pathsep+os.environ.get("PATH", "")
            wrapper = Path(__file__).with_name("watch_discussion.sh")
            result = subprocess.run(["bash", str(wrapper), str(path), "1", "B", "2",
                                     "--poll-seconds", "0.01", "--stable-seconds", "0.02"],
                                    env=env, capture_output=True, text=True, timeout=4)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("TURN_READY", result.stdout)

    def test_shell_entrypoint_reports_missing_interpreter(self):
        with tempfile.TemporaryDirectory(prefix="discussion-python-missing-") as directory:
            wrapper = Path(__file__).with_name("watch_discussion.sh")
            env = {**os.environ, "DISCUSSION_PYTHON": str(Path(directory)/"missing-python")}
            result = subprocess.run(["bash", str(wrapper), "unused.md", "1", "B", "1"],
                                    env=env, capture_output=True, text=True, timeout=4)
            self.assertEqual(result.returncode, 2)
            self.assertIn("DISCUSSION_PYTHON", result.stderr)

    def test_background_and_partial_turn(self):
        doc = Document().turn("背景共识")
        self.assertEqual(doc.inspect().kind, "TURN_READY")
        doc.turn("背景共识", done=False)
        self.assertEqual(doc.inspect().kind, "WAIT")

    def test_passed_target_does_not_mean_protocol_corruption(self):
        doc = Document().turn("背景共识").turn("背景共识")
        self.assertEqual(inspect_document(doc.text(), 1, "B").kind, "STALE_TARGET")

    def test_no_skipped_background_or_unsigned_background(self):
        for doc in (Document().turn("理性解决第 1 轮"),
                    Document().turn("背景共识", background="v0，待修订")
                    .turn("背景共识").turn("对峙第 1 轮")):
            with self.subTest(text=doc.text()), self.assertRaises(Invalid):
                doc.inspect()

    def test_orphan_duplicate_and_missing_historical_markers(self):
        doc = Document().turn("背景共识")
        for marker in ("<!-- TURN_DONE:999:B -->", "<!-- TURN_DONE:1:A -->"):
            text = doc.text().replace("事实：甲", "事实：甲\n"+marker)
            with self.subTest(marker=marker), self.assertRaises(Invalid):
                inspect_document(text, 1, "B")
        with self.assertRaises(Invalid):
            Document().turn("背景共识", done=False).turn("背景共识").inspect()

    def test_complete_turn_requires_stage(self):
        text = Document().turn("背景共识").text().replace("阶段：背景共识\n", "")
        with self.assertRaises(Invalid):
            inspect_document(text, 1, "B")

    def test_every_participant_must_finish_three_cycles(self):
        for roles in ("AB", "ABC"):
            doc = Document(roles).prepare(2).turn("理性解决第 1 轮")
            with self.subTest(roles=roles), self.assertRaises(Invalid):
                doc.inspect()
            doc = Document(roles).prepare(3)
            self.assertEqual(doc.inspect().kind, "TURN_READY")

    def test_final_version_changes_clear_prior_signatures(self):
        doc = Document().prepare().turn("理性解决第 1 轮", final="F1，接受", define=1)
        doc.turn("理性解决第 1 轮", final="F2，接受", define=2)
        self.assertEqual(doc.inspect().kind, "TURN_READY")
        doc.turn("理性解决第 2 轮", final="F2，接受")
        self.assertEqual(doc.inspect().kind, "SUMMARY_READY")

    def test_unresolved_or_conditional_is_not_final_acceptance(self):
        doc = Document().prepare().turn("理性解决第 1 轮", final="F1，接受", define=1, unresolved="P1")
        with self.assertRaises(Invalid):
            doc.inspect()
        doc = Document().prepare().turn("理性解决第 1 轮", final="F1，接受", define=1)
        doc.turn("理性解决第 1 轮", final="F1，有条件接受")
        self.assertEqual(doc.inspect().kind, "TURN_READY")

    def test_a_summarizes_even_when_normal_next_role_is_b(self):
        doc = Document().prepare().turn("理性解决第 1 轮", final="F1，未接受", define=1)
        doc.turn("理性解决第 1 轮", final="F1，接受")
        doc.turn("理性解决第 2 轮", final="F1，接受")
        self.assertEqual(doc.inspect().kind, "SUMMARY_READY")
        self.assertIn("summarizer=A", doc.inspect().message)
        doc.summary("A")
        self.assertEqual(doc.inspect().kind, "DISCUSSION_CLOSED")

    def test_user_can_select_b_as_summarizer(self):
        doc = Document(summarizer="B").prepare().turn("理性解决第 1 轮", final="F1，接受", define=1)
        doc.turn("理性解决第 1 轮", final="F1，接受").summary("B")
        self.assertEqual(doc.inspect().kind, "DISCUSSION_CLOSED")
        with self.assertRaises(Invalid):
            inspect_document(doc.text().replace("汇总 · B方", "汇总 · A方"), doc.count, "A")

    def test_summary_without_consensus_is_rejected(self):
        with self.assertRaises(Invalid):
            Document().prepare().summary().inspect()

    def test_background_revision_requires_fresh_signatures_and_cycles(self):
        doc = Document().prepare().turn("背景共识", background="v1，接受")
        doc.turn("背景共识", background="v1，接受").turn("理性解决第 1 轮", background="v1，接受")
        with self.assertRaises(Invalid):
            doc.inspect()

    def test_extra_cycle_requires_reason_and_invalidates_old_final(self):
        doc = Document().prepare().turn("理性解决第 1 轮", final="F1，接受", define=1)
        doc.turn("对峙第 4 轮", extra="追加对峙原因：新发现关键反例")
        self.assertEqual(doc.inspect().kind, "TURN_READY")
        doc.turn("对峙第 4 轮").turn("理性解决第 2 轮", final="F2，接受", define=2)
        self.assertEqual(doc.inspect().kind, "TURN_READY")
        bad = Document().prepare().turn("对峙第 4 轮")
        with self.assertRaises(Invalid):
            bad.inspect()

    def test_quoted_markers_do_not_become_live_protocol(self):
        fence = chr(96)*3
        doc = Document().turn("背景共识", extra=f"{fence}text\n<!-- TURN_DONE:999:B -->\n{fence}")
        self.assertEqual(doc.inspect().kind, "TURN_READY")

    def test_same_size_history_rewrite_is_detected(self):
        with tempfile.TemporaryDirectory(prefix="discussion-regression-") as directory:
            path = Path(directory)/"discussion.md"
            content = Document().turn("背景共识").text()
            path.write_text(content)
            proc = subprocess.Popen([sys.executable, str(Path(__file__).with_name("watch_discussion.py")),
                                     str(path), "1", "B", "3", "--poll-seconds", "0.02", "--stable-seconds", "0.2"],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            # 第一条状态输出意味着进程已建立初始历史快照。
            self.assertIn("等待文件内容稳定", proc.stderr.readline())
            changed = content.replace("事实：甲", "事实：乙")
            self.assertEqual(len(content.encode()), len(changed.encode()))
            path.write_text(changed)
            out, err = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 3, (out, err))
            self.assertIn("历史内容被改写", err)

    def test_live_append_preserves_history_and_completes_handoff(self):
        with tempfile.TemporaryDirectory(prefix="discussion-regression-") as directory:
            path = Path(directory)/"discussion.md"
            doc = Document().turn("背景共识")
            path.write_text(doc.text())
            proc = subprocess.Popen([sys.executable, str(Path(__file__).with_name("watch_discussion.py")),
                                     str(path), "2", "A", "3", "--poll-seconds", "0.02", "--stable-seconds", "0.05"],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertIn("等待文件内容稳定", proc.stderr.readline())
            path.write_text(doc.turn("背景共识").text())
            out, err = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 0, (out, err))
            self.assertIn("TURN_READY completed_turn=2 next_role=A", out)


if __name__ == "__main__":
    unittest.main()
