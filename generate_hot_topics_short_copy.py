from __future__ import annotations

import re
from pathlib import Path

ROOT_PHRASES = [
    "成本的｜便宜又有面子/花大钱干的/十分之一时间或金钱/如何偷懒/如何贪小便宜",
    "人群的｜不懂装懂爱挑战/第一次体验/VIP/弱势群体",
    "奇葩的｜脑回路有病/外行人不知道/黑心内幕揭秘",
    "最差的｜难吃难看难用/差评最多/贬值最快/最没面子/拼多多9块9的",
    "反差的｜身份/对比/南北/古今/中外/男女/穷富/品牌的反差",
    "怀旧的｜20年前/具体朝代/前男友前女友的记忆点",
    "荷尔蒙的｜好找对象/魅力变弱/吸引力翻转",
    "头牌的｜名人明星名企名校/销量最好/最贵/最有面子",
]


def _clean(text: str) -> str:
    return text.rstrip("。. ").strip()


def parse_topics(source: Path) -> list[dict]:
    """Parse numbered topics with optional 卖点/交付行."""
    topics = []
    current = None
    for raw_line in source.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        match = re.match(r"^(\d+)\)\s+(.*)$", line)
        if match:
            if current:
                topics.append(current)
            current = {
                "id": match.group(1),
                "title": match.group(2),
                "sell": None,
                "deliver": None,
            }
            continue
        if not current:
            continue
        if "卖点：" in line:
            current["sell"] = _clean(line.split("卖点：", 1)[1])
        elif "交付：" in line:
            current["deliver"] = _clean(line.split("交付：", 1)[1])
    if current:
        topics.append(current)
    return topics


def _pick_root(idx: int) -> str:
    return ROOT_PHRASES[idx % len(ROOT_PHRASES)]


def build_copy(topics: list[dict]) -> str:
    lines = [
        "## AI 爆款选题短时睥睨文案",
        "",
        "2025 爆款词根：成本的/人群的/奇葩的/最差的/反差的/怀旧的/荷尔蒙/头牌。",
        "补充语义：闭门/一天搞定/100条/逆袭/双赛道/黑马岗位/出海/赞助/避坑。",
        "",
    ]
    default_pain = "拖慢进度的通常是落地路径、成交话术和可直接使用的模板。"
    for idx, topic in enumerate(topics):
        title = topic["title"]
        sell = topic.get("sell") or "直接拆成可复制路径"
        deliver = topic.get("deliver") or "完整 SOP 与模板包"
        topic_id = topic["id"]
        root = _pick_root(idx)
        lines.extend(
            [
                f"### {topic_id}) {title}",
                f"- 爆款词根：{root}",
                f"- 开场：{title}，{sell}。",
                f"- 痛点：{default_pain}",
                f"- 结果：拿到{deliver}，照抄也能上线/成交。",
                f"- CTA：评论/私信「{topic_id}」领取行动版 SOP，先到先得。",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_voiceover(topics: list[dict]) -> str:
    lines = [
        "## AI 爆款选题口播文案",
        "",
        "节奏：钩子（1 句）→ 痛点（1 句）→ 结果（1 句）→ CTA（1 句），控制在 15-20 秒。",
        "",
    ]
    default_pain = "多数人卡在不会拆路径、不会成交、没有现成模板。"
    for idx, topic in enumerate(topics):
        title = topic["title"]
        sell = topic.get("sell") or "直接拆成可复制路径"
        deliver = topic.get("deliver") or "完整 SOP 与模板包"
        topic_id = topic["id"]
        root = _pick_root(idx)
        root_head = root.split("｜", 1)[0].rstrip("的")
        hook = f"{title}——{root_head}的速成打法"
        script = (
            f"钩子：{hook}。"
            f"痛点：{default_pain}"
            f"结果：{deliver}，跟着抄就能上线成交。"
            f"CTA：私信「{topic_id}」领行动版 SOP。"
        )
        lines.extend(
            [
                f"### {topic_id}) {title}",
                f"- 口播脚本：{script}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    source = Path("ai-paid-hot-topics/ai-paid-hot-topics.md")
    target = Path("ai-paid-hot-topics/hot-topics-short-copy.md")
    voiceover_target = Path("ai-paid-hot-topics/hot-topics-voiceover.md")
    if not source.exists():
        raise FileNotFoundError(f"找不到源文件：{source}")

    topics = parse_topics(source)
    if not topics:
        raise ValueError("未从源文件解析到任何选题。")

    target.write_text(build_copy(topics), encoding="utf-8")
    voiceover_target.write_text(build_voiceover(topics), encoding="utf-8")


if __name__ == "__main__":
    main()
