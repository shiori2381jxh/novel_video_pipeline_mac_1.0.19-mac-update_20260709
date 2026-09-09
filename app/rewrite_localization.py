"""Deterministic helpers for task-local proper-noun rewrite localization."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata


ALLOWED_REPLACEMENT_CATEGORIES = frozenset(
    {"人名", "地名", "家族名", "组织名", "机构名", "种族名"}
)
_CATEGORY_ALIASES = {
    "地点": "地名",
    "種族名": "种族名",
}
_GENERIC_SOURCES = frozenset(
    {
        "老师", "同学", "先生", "小姐", "少女", "少年", "主人公", "勇者", "国王",
        "王子", "公主", "彼", "彼女", "教師", "先生", "少女", "少年", "勇者",
        "国王", "王子", "王女", "主人公",
    }
)
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.IGNORECASE | re.DOTALL)
_JAPANESE_KANA_RE = re.compile(r"[\u3040-\u30ff]")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")

# 无假名的日文、中文都可能只由汉字组成，不能仅按「出现汉字」判为中文。
# 这些是两种文字中较有区分度的常见字；其余难以可靠判断的情况交给 unknown
# 分支，提示词会要求模型沿用输入语言，而不会强制转成简体中文。
_JAPANESE_DISTINCTIVE_CHARS = frozenset("駅緊働届広沢浜渋栄鉄辺気")
_CHINESE_SIMPLIFIED_DISTINCTIVE_CHARS = frozenset("这车却她们个后发与为从来里东书见听说话门开进")
_FALLBACK_TARGETS = {
    "zh": {
        "人名": ("沈言", "顾川", "苏晚", "陆宁", "程墨", "许星", "温然", "江遥"),
        "地名": ("云岚城", "听潮镇", "临川郡", "栖霞山", "明月湾", "长风原"),
        "家族名": ("沈氏", "顾家", "苏门", "陆族", "程府", "许氏"),
        "组织名": ("玄霄会", "长明盟", "归云堂", "听风司", "青梧社", "北斗营"),
        "机构名": ("明德书院", "司天监", "巡夜司", "鸿胪馆", "济世堂", "观星台"),
        "种族名": ("云裔", "岚民", "星族", "河灵", "霜裔", "木灵"),
    },
    "ja": {
        "人名": ("ハル", "ミナト", "アオイ", "ユズ", "ソラ", "ナギ", "レン", "カナ"),
        "地名": ("朝凪町", "星見村", "白波島", "風見丘", "月影谷", "霞ヶ浦"),
        "家族名": ("朝霧家", "白波家", "風見家", "月城家", "星野家", "桜庭家"),
        "组织名": ("暁の会", "白波連盟", "風見団", "月影衆", "星詠み隊", "霞の社"),
        "机构名": ("星見学園", "朝凪研究所", "月影庁", "白波診療所", "風見図書館", "霞ヶ丘学院"),
        "种族名": ("月の民", "星の民", "風の民", "霞の民", "海の民", "森の民"),
    },
}


@dataclass(frozen=True)
class RewriteLanguage:
    code: str
    confidence: float
    warning: str = ""


@dataclass(frozen=True)
class Replacement:
    category: str
    source: str
    target: str
    notes: str
    batch: int
    local_replace_safe: bool


@dataclass(frozen=True)
class RewriteBatchResult:
    rewritten_text: str
    replacements: tuple[Replacement, ...]
    warnings: tuple[str, ...]


def detect_rewrite_language(text: str) -> RewriteLanguage:
    """Infer Chinese or Japanese from stable script evidence, without translation."""
    value = str(text or "")
    kana = len(_JAPANESE_KANA_RE.findall(value))
    cjk = len(_CJK_RE.findall(value))
    latin = len(_LATIN_RE.findall(value))
    signal = kana + cjk + latin
    if signal < 4:
        return RewriteLanguage("unknown", 0.0, "正文过短或文字特征不足，无法可靠判定原文语言")
    if kana >= 2 and kana / max(1, signal) >= 0.12:
        return RewriteLanguage("ja", min(1.0, kana / 10.0))

    japanese_distinctive = sum(char in _JAPANESE_DISTINCTIVE_CHARS for char in value)
    chinese_distinctive = sum(char in _CHINESE_SIMPLIFIED_DISTINCTIVE_CHARS for char in value)
    if japanese_distinctive > chinese_distinctive and japanese_distinctive:
        return RewriteLanguage("ja", min(0.88, 0.6 + japanese_distinctive / max(signal, 1)))
    if chinese_distinctive > japanese_distinctive and chinese_distinctive:
        return RewriteLanguage("zh", min(0.88, 0.6 + chinese_distinctive / max(signal, 1)))
    if cjk >= 2 and kana == 0:
        return RewriteLanguage(
            "unknown",
            0.0,
            "正文只有难以区分的汉字，未强制判为中文；模型须保持输入的原始语言。",
        )
    return RewriteLanguage("unknown", 0.0, "正文语言特征混合，改写时将要求保持原有主语言")


def build_structured_rewrite_prompt(
    *,
    skill: str,
    language: RewriteLanguage,
    known_replacements: list[Replacement],
    batch_index: int,
    batch_count: int,
    allowed_categories: set[str] | None = None,
) -> tuple[str, str]:
    language_rule = {
        "ja": "必须只输出自然日语；不得翻译成中文、英语或其他语言。新专名须采用自然的日式命名。",
        "zh": "必须只输出自然简体中文；不得翻译成日语、英语或其他语言。新专名须采用自然的中文命名。",
    }.get(language.code, "必须保持输入正文的主语言；不得执行翻译。")
    category_rule = "、".join(sorted(allowed_categories)) if allowed_categories else "人名、地名、家族名、组织名、机构名、种族名"
    system = (
        "你是同语种小说本地化润色编辑。你不是翻译器。"
        "保留剧情事实、人物关系、因果、叙事视角、关键设定、结局和有效信息量；"
        "不得新增或删减事件、人物、设定、心理活动或结局。"
        f"{language_rule}"
        "已有替换清单是最高优先级：同一原词必须始终使用同一个目标词。"
        f"仅可为跨段稳定的专名提出新映射，类别仅限{category_rule}。"
        "新名称必须与原名称明显不同，不能只替换少数字符、保留主体读音或沿用同一首音。"
        "只返回一个 JSON 对象，不得使用 Markdown 或解释。"
    )
    replacements = [
        {
            "category": item.category,
            "source": item.source,
            "target": item.target,
            "notes": item.notes,
        }
        for item in known_replacements
    ]
    user = (
        f"当前为第 {batch_index}/{batch_count} 批。\n"
        "【洗稿 Skill（高优先级风格规则）】\n"
        f"{str(skill or '').strip() or '以自然、清晰的叙事表达润色正文。'}\n\n"
        "【已有替换清单】\n"
        f"{json.dumps(replacements, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "收到正文后，只返回："
        '{"rewritten_text":"本批完整润色正文","new_replacements":['
        '{"category":"人名","source":"原名","target":"新名","notes":"依据"}'
        '],"warnings":[]}'
    )
    return system, user


def parse_structured_rewrite_response(
    raw: str,
    *,
    source_text: str,
    batch_index: int,
    known_replacements: list[Replacement],
    allowed_categories: set[str] | None = None,
) -> RewriteBatchResult:
    value = str(raw or "").strip()
    fence = _FENCE_RE.fullmatch(value)
    if fence:
        value = fence.group(1).strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("模型没有返回有效的洗稿 JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("模型洗稿结果必须是 JSON 对象")
    rewritten_text = parsed.get("rewritten_text")
    if not isinstance(rewritten_text, str) or not rewritten_text.strip():
        raise ValueError("模型洗稿结果缺少非空 rewritten_text")
    raw_replacements = parsed.get("new_replacements")
    raw_warnings = parsed.get("warnings")
    if not isinstance(raw_replacements, list) or not isinstance(raw_warnings, list):
        raise ValueError("模型洗稿结果必须包含数组 new_replacements 和 warnings")

    existing = {item.source: item for item in known_replacements}
    replacements: list[Replacement] = []
    ignored_categories: list[str] = []
    for raw_item in raw_replacements:
        item = _validate_replacement(
            raw_item,
            source_text=source_text,
            batch_index=batch_index,
        )
        if allowed_categories is not None and item.category not in allowed_categories:
            ignored_categories.append(item.category)
            continue
        old = existing.get(item.source)
        if old is not None:
            if old.target != item.target:
                raise ValueError(f"专名映射冲突：{item.source} 已映射为 {old.target}")
            continue
        existing[item.source] = item
        replacements.append(item)
    warnings = [str(item).strip() for item in raw_warnings if str(item).strip()]
    if ignored_categories:
        warnings.append("已忽略未选替换类别：" + "、".join(sorted(set(ignored_categories))))
    return RewriteBatchResult(
        rewritten_text=rewritten_text.strip(),
        replacements=tuple(replacements),
        warnings=tuple(warnings),
    )


def validate_rewrite_quality(
    *,
    source_text: str,
    rewritten_text: str,
    language: RewriteLanguage,
    min_ratio: float,
    max_ratio: float,
) -> list[str]:
    source_length = len(str(source_text or "").strip())
    rewritten_length = len(str(rewritten_text or "").strip())
    errors: list[str] = []
    if not rewritten_length:
        return ["洗稿结果为空"]
    if source_length >= 8:
        ratio = rewritten_length / source_length
        if ratio < max(0.01, float(min_ratio)):
            errors.append(f"洗稿结果长度比例过低：{ratio:.2f}")
        if ratio > max(float(min_ratio), float(max_ratio)):
            errors.append(f"洗稿结果长度比例过高：{ratio:.2f}")
    if language.code in {"ja", "zh"} and language.confidence >= 0.35:
        rewritten_language = detect_rewrite_language(rewritten_text)
        if rewritten_language.code != language.code:
            display = "日语" if language.code == "ja" else "中文"
            errors.append(f"洗稿结果未保持{display}输出")
    return errors


def apply_replacements(text: str, replacements: list[Replacement]) -> str:
    """Apply mappings in one pass, so replacement targets never cascade."""
    value = str(text or "")
    mapping: dict[str, str] = {}
    for item in replacements:
        if item.local_replace_safe and item.source and item.target:
            mapping.setdefault(item.source, item.target)
    if not mapping:
        return value

    # 通过原文的一次正则匹配完成替换。即便「阿明→陈舟」且「陈舟→东方」
    # 同时存在，前一个映射刚写入的「陈舟」也不会在同一次处理里再被替换。
    sources = sorted(mapping, key=lambda source: (-len(source), source))
    matcher = re.compile("|".join(re.escape(source) for source in sources))
    return matcher.sub(lambda matched: mapping[matched.group(0)], value)


def find_residual_sources(text: str, replacements: list[Replacement]) -> list[str]:
    value = str(text or "")
    return [
        item.source
        for item in sorted(replacements, key=lambda item: (-len(item.source), item.source))
        if item.source in value
    ]


def _validate_replacement(raw_item: object, *, source_text: str, batch_index: int) -> Replacement:
    if not isinstance(raw_item, dict):
        raise ValueError("模型返回了格式错误的专名映射")
    category = _CATEGORY_ALIASES.get(str(raw_item.get("category", "")).strip(), str(raw_item.get("category", "")).strip())
    source = str(raw_item.get("source", "")).strip()
    target = str(raw_item.get("target", "")).strip()
    notes = str(raw_item.get("notes", "")).strip()
    if category not in ALLOWED_REPLACEMENT_CATEGORIES:
        raise ValueError(f"专名映射类别无效：{category or '空'}")
    if not source or not target:
        raise ValueError("专名映射的原词和新词不能为空")
    if len(source) > 120 or len(target) > 120:
        raise ValueError("专名映射长度超过安全上限")
    if source not in str(source_text or ""):
        raise ValueError(f"专名映射原词未出现在本批原文：{source}")
    if _names_too_similar(source, target):
        raise ValueError(f"专名映射的新名称与原名过于相近：{source}")
    return Replacement(
        category=category,
        source=source,
        target=target,
        notes=notes,
        batch=int(batch_index),
        local_replace_safe=len(source) >= 2 and source not in _GENERIC_SOURCES,
    )


def extract_rejected_replacement_sources(raw: str, source_text: str) -> list[dict[str, str]]:
    """Recover usable source/category pairs from a rejected model JSON response."""
    value = str(raw or "").strip()
    fence = _FENCE_RE.fullmatch(value)
    if fence:
        value = fence.group(1).strip()
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return []
    items = payload.get("new_replacements") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    text = str(source_text or "")
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        category = _CATEGORY_ALIASES.get(
            str(raw_item.get("category", "")).strip(),
            str(raw_item.get("category", "")).strip(),
        )
        source = str(raw_item.get("source", "")).strip()
        if category not in ALLOWED_REPLACEMENT_CATEGORIES or not source or source not in text:
            continue
        if source not in seen:
            found.append({"category": category, "source": source})
            seen.add(source)
    return found


def build_deterministic_fallback_replacements(
    candidates: list[dict[str, str]],
    source_text: str,
    batch_index: int,
    known_replacements: list[Replacement],
) -> list[Replacement]:
    """Create stable, validated substitutes after the model returns an invalid name."""
    language = detect_rewrite_language(source_text).code
    pools = _FALLBACK_TARGETS.get(language, _FALLBACK_TARGETS["zh"])
    existing = {item.source for item in known_replacements}
    reserved_targets = {item.target for item in known_replacements}
    result: list[Replacement] = []
    for candidate in candidates:
        category = str(candidate.get("category") or "").strip()
        source = str(candidate.get("source") or "").strip()
        if not source or source in existing or source not in str(source_text or ""):
            continue
        pool = pools.get(category, ())
        if not pool:
            continue
        offset = int.from_bytes(
            hashlib.sha256(f"{category}\0{source}".encode("utf-8")).digest()[:4], "big"
        ) % len(pool)
        target = next(
            (
                pool[(offset + index) % len(pool)]
                for index in range(len(pool))
                if pool[(offset + index) % len(pool)] not in reserved_targets
                and not _names_too_similar(source, pool[(offset + index) % len(pool)])
            ),
            "",
        )
        if not target:
            continue
        replacement = _validate_replacement(
            {
                "category": category,
                "source": source,
                "target": target,
                "notes": "自动兜底：模型改名校验失败",
            },
            source_text=source_text,
            batch_index=batch_index,
        )
        result.append(replacement)
        existing.add(source)
        reserved_targets.add(target)
    return result


def _names_too_similar(source: str, target: str) -> bool:
    left = _compact_name(source)
    right = _compact_name(target)
    if not left or not right or left == right or left in right or right in left:
        return True
    if _edit_distance(left, right) <= max(1, min(len(left), len(right)) // 3):
        return True
    if _is_kana(left) and _is_kana(right) and _to_katakana(left)[:1] == _to_katakana(right)[:1]:
        return True
    return False


def _compact_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return "".join(char for char in normalized if char not in " ・·．.ー－-_/\\")


def _is_kana(value: str) -> bool:
    return bool(value) and all("ぁ" <= char <= "ゖ" or "ァ" <= char <= "ヺ" for char in value)


def _to_katakana(value: str) -> str:
    return "".join(chr(ord(char) + 0x60) if "ぁ" <= char <= "ゖ" else char for char in value)


def _edit_distance(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, 1):
        current = [left_index]
        for right_index, right_char in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]
