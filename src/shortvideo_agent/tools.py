"""Deterministic business tools. No model decision loop lives here.

Grounding uses exact source statements plus a small public editorial allowlist.
Unverified free text is rejected rather than treated as semantically verified.
"""

import copy
import hashlib
import json
import math
import re
import unicodedata
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_CEILING, localcontext

from .contracts import BRIEF, CHECK, MATERIALS, POSITIVE, SCRIPT, ValidationError, obj, validate
from .materials import validate_assets


def normalize(text: str) -> str:
    """Ignore cosmetic punctuation; retain numeric separators and units."""
    text = unicodedata.normalize("NFKC", text).casefold()
    return "".join(char for index, char in enumerate(text)
                   if char.isalnum() or char in "%‰+-−=<>$¥€£"
                   or (not char.isspace() and 0 < index < len(text) - 1
                       and text[index - 1].isdigit() and text[index + 1].isdigit()))


EDITORIAL_POLICY = {
    "name": "exact_source_and_editorial_allowlist_v1",
    "description": "产品事实须逐字引用素材及全部限定；其余文案仅使用下列连接短语。未知表述会被拦截，不代表其一定为假。",
    "neutral_titles": ["功能演示", "产品功能介绍", "创作功能小课堂", "一起看功能"],
    "neutral_visuals": [
        "展示片头标题", "展示所引素材中的功能说明", "展示旁白对应的素材原文",
        "展示分镜字幕", "展示结束卡片", "镜头推近", "镜头切换", "画面渐入", "画面渐出",
    ],
    "neutral_copy": [
        "先看功能", "再看细节", "接下来", "一起看看吧", "按需选择",
        "看看是否适合你的创作需求", "完成后再检查一遍", "先看清楚再动手",
        "这里展示素材中的产品说明", "今天先看到这里", "字幕先别急", "一步一步来",
        "效果以实际使用为准", "演示画面仅供参考",
    ],
}


def _terms(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9_]+", text.casefold()))
    for segment in re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]+", text):
        words.update(segment[index:index + 2] for index in range(len(segment) - 1))
        if len(segment) == 1:
            words.add(segment)
    return words


def search_materials(materials: dict, query: str, *, product_id: str | None = None,
                     limit: int = 5) -> dict:
    validate(materials, MATERIALS)
    validate(query, {"type": "string", "minLength": 1})
    validate(limit, {"type": "integer", "minimum": 1, "maximum": 10})
    query_normalized = normalize(query)
    if not any(char.isalnum() for char in query_normalized):
        raise ValidationError("query must contain letters or numbers")
    query_terms = _terms(unicodedata.normalize("NFKC", query))
    matches = []
    for material in materials["materials"]:
        if product_id is not None and material["product_id"] != product_id:
            continue
        text = " ".join([material["material_id"], material["product_id"], material["title"],
                         *material["tags"], *[fact["statement"] for fact in material["facts"]],
                         *[qualifier for fact in material["facts"] for qualifier in fact["qualifiers"]]])
        phrase_match = query_normalized in normalize(text)
        score = len(query_terms & _terms(unicodedata.normalize("NFKC", text))) + (3 if phrase_match else 0)
        if score:
            matches.append({**copy.deepcopy(material), "score": score})
    matches.sort(key=lambda match: (-match["score"], match["material_id"]))
    return {
        "query": query, "product_id": product_id, "materials_synthetic": materials["synthetic"], "matched_count": len(matches),
        "returned_count": min(limit, len(matches)), "truncated": len(matches) > limit,
        "matches": matches[:limit], "grounding_policy": copy.deepcopy(EDITORIAL_POLICY),
        "limitations": ["本地关键词检索，不进行语义推断；命中素材不代表查询中的其他能力已获证实。"],
    }


def script_identity(script: dict) -> dict:
    """Bind checks to content and revision, ignoring tool-computed estimate fields."""
    validate(script, SCRIPT)
    payload = copy.deepcopy(script)
    payload.pop("estimated_total_seconds")
    for scene in payload["scenes"]:
        scene.pop("estimated_duration_seconds")
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {"script_revision": script["revision"], "script_sha256": hashlib.sha256(canonical).hexdigest()}


@dataclass(frozen=True)
class TimingPolicy:
    spoken_characters_per_second: float = 4.0
    spoken_words_per_second: float = 2.5
    reading_characters_per_second: float = 5.0
    reading_words_per_second: float = 3.0
    punctuation_pause_seconds: float = 0.2

    def __post_init__(self):
        for key, value in asdict(self).items():
            schema = {"type": "number", "minimum": 0} if key == "punctuation_pause_seconds" else POSITIVE
            validate(value, schema, f"timing_policy.{key}")


def _text_time(text: str, character_rate: float, word_rate: float, punctuation_pause: float) -> Decimal:
    text = unicodedata.normalize("NFKC", text)
    words = re.findall(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*", text)
    remainder = re.sub(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*", "", text)
    characters = sum(char.isalnum() or char in "%‰" for char in remainder)
    punctuation = len(re.findall(r"[，,。.!！?？;；:：]", text))
    return (Decimal(characters) / Decimal(str(character_rate))
            + Decimal(len(words)) / Decimal(str(word_rate))
            + Decimal(punctuation) * Decimal(str(punctuation_pause)))


def _ceil_tenth(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_CEILING)


def _as_number(value: Decimal) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValidationError("Calculated duration is outside the supported finite numeric range")
    return result


def estimate_duration(script: dict, target_duration_seconds: float,
                      *, policy: TimingPolicy | None = None) -> dict:
    validate(script, SCRIPT)
    validate(target_duration_seconds, POSITIVE)
    policy = policy or TimingPolicy()
    scenes, total = [], Decimal("0")
    numeric_fields = [target_duration_seconds, *[
        value for scene in script["scenes"] for value in (scene["pause_seconds"], scene["min_visual_seconds"])]]
    with localcontext() as context:
        context.prec = max(50, max(len(str(value)) for value in numeric_fields) + 330)
        for scene in script["scenes"]:
            voiceover = _text_time(scene["voiceover"], policy.spoken_characters_per_second,
                                   policy.spoken_words_per_second, policy.punctuation_pause_seconds)
            subtitle = _text_time(scene["subtitle"], policy.reading_characters_per_second,
                                  policy.reading_words_per_second, 0)
            duration = _ceil_tenth(max(voiceover, subtitle, Decimal(str(scene["min_visual_seconds"])))
                                   + Decimal(str(scene["pause_seconds"])))
            total += duration
            scenes.append({"scene_id": scene["scene_id"], "voiceover_seconds": _as_number(_ceil_tenth(voiceover)),
                           "subtitle_reading_seconds": _as_number(_ceil_tenth(subtitle)),
                           "min_visual_seconds": scene["min_visual_seconds"], "pause_seconds": scene["pause_seconds"],
                           "estimated_duration_seconds": _as_number(duration)})
        target = Decimal(str(target_duration_seconds))
        over_by = max(Decimal("0"), total - target)
    result = {
        "tool": "estimate_duration", **script_identity(script), "passed": total <= target,
        "summary": "预计时长符合上限" if total <= target else "预计时长超过上限，需要修改脚本或说明无法满足",
        "details": {
            "target_duration_seconds": target_duration_seconds, "estimated_total_seconds": _as_number(total),
            "over_by_seconds": _as_number(over_by), "scenes": scenes, "policy": asdict(policy),
            "method": "每镜 max(旁白含标点停顿的时长, 字幕阅读时长, 必要画面占用) + 额外停顿，向上取整到0.1秒后求和。",
            "limitations": ["中文及其他非英文文字按字符、数字逐位、英文按单词估算；不能代表实际成片时长。",
                            "忽略输入脚本中自报的估时；旁白与字幕同时呈现，取较长值而非相加。"],
        },
    }
    validate(result, CHECK)
    return result


def _field_texts(script: dict):
    yield "title", script["title"], None
    for scene in script["scenes"]:
        for field in ("visual", "voiceover", "subtitle"):
            yield f"scenes.{scene['scene_id']}.{field}", scene[field], scene


def _uncovered(text: str, phrases: list[str]) -> str:
    """Consume phrases at each position; never merge leftovers into a new phrase."""
    text = normalize(text)
    candidates = sorted({normalize(phrase) for phrase in phrases if normalize(phrase)}, key=lambda item: (-len(item), item))
    unmatched, index = [], 0
    while index < len(text):
        match = next((phrase for phrase in candidates if text.startswith(phrase, index)), None)
        if match:
            index += len(match)
        else:
            unmatched.append(text[index])
            index += 1
    return "".join(unmatched)


def check_rules(script: dict, materials: dict, rules: dict, *, product_id: str | None = None) -> dict:
    validate(script, SCRIPT)
    validate_assets(materials, rules)
    product_id = product_id or rules["product_id"]
    issues, verified, allowed_claims = [], [], {}

    def issue(code: str, location: str, message: str, **evidence):
        issues.append({"code": code, "location": location, "message": message, **evidence})

    if product_id != rules["product_id"]:
        issue("product_scope_mismatch", "rules.product_id", "品牌规则不属于当前产品")
    index = {(material["material_id"], fact["fact_id"]): (material, fact)
             for material in materials["materials"] for fact in material["facts"]}
    scene_ids = set()
    for scene in script["scenes"]:
        scene_id = scene["scene_id"]
        if scene_id in scene_ids:
            issue("duplicate_scene_id", f"scenes.{scene_id}", "分镜编号必须唯一")
        scene_ids.add(scene_id)
        allowed_claims[id(scene)] = []
        if not scene["voiceover"].strip() and not scene["subtitle"].strip():
            issue("missing_scene_text", f"scenes.{scene_id}", "每镜至少有旁白或字幕")
        for citation in scene["citations"]:
            location = f"scenes.{scene_id}.citations"
            pair = (citation["material_id"], citation["fact_id"])
            if pair not in index:
                issue("unknown_source", location, "来源和事实 ID 不匹配或不存在", **citation)
                continue
            material, fact = index[pair]
            if material["product_id"] != product_id:
                issue("wrong_product_source", location, "引用属于其他产品", **citation)
                continue
            expected = "；".join([fact["statement"], *fact["qualifiers"]])
            if not any(char.isalnum() for char in normalize(expected)):
                issue("invalid_source_text", location, "素材事实必须包含有效文字", **citation)
                continue
            if normalize(citation["claim"]) != normalize(expected):
                issue("claim_not_supported", location, "引用必须是素材原句并保留全部限定，不能扩大事实含义",
                      **citation, supported_text=expected)
                continue
            if not any(normalize(citation["claim"]) in normalize(scene[field])
                       for field in ("voiceover", "subtitle", "visual")):
                issue("unused_citation", location, "声明引用的事实没有出现在对应分镜中", **citation)
                continue
            allowed_claims[id(scene)].append(citation["claim"])
            verified.append({"scene_id": scene_id, **citation})

    all_claims = [citation["claim"] for citation in verified]
    if not verified:
        issue("missing_product_evidence", "script", "至少需要一条已核验且出现在分镜中的产品事实")
    fields = list(_field_texts(script))
    for location, text, scene in fields:
        if location == "title":
            neutral = EDITORIAL_POLICY["neutral_titles"]
            claims = all_claims
        elif location.endswith(".visual"):
            neutral = EDITORIAL_POLICY["neutral_visuals"]
            claims = allowed_claims[id(scene)]
        else:
            neutral = EDITORIAL_POLICY["neutral_copy"]
            claims = allowed_claims[id(scene)]
        remainder = _uncovered(text, [*neutral, *claims])
        if remainder:
            issue("unverified_text", location, "存在无法由素材原句或已公开连接短语覆盖的文字；请改写或补充资料",
                  uncovered_text=remainder)

    for rule in rules["rules"]:
        normalized = normalize(rule["value"])
        if not normalized:
            issue("invalid_rule", f"rules.{rule['rule_id']}", "规则内容必须包含有效文字")
        elif rule["kind"] == "forbidden_phrase":
            for location, text, _ in fields:
                if normalized in normalize(text):
                    issue("forbidden_phrase", location, rule["description"], rule_id=rule["rule_id"])
        elif not any(normalized in normalize(text) for location, text, _ in fields
                     if location.endswith((".voiceover", ".subtitle"))):
            issue("missing_disclaimer", "script", rule["description"], rule_id=rule["rule_id"])

    result = {
        "tool": "check_rules", **script_identity(script), "passed": not issues,
        "summary": "品牌规则及保守事实核验通过" if not issues else "检查未通过，需要按问题位置修正或说明无法满足",
        "details": {"product_id": product_id, "materials_synthetic": materials["synthetic"],
                    "rules_synthetic": rules["synthetic"], "issues": issues, "verified_citations": verified,
                    "grounding_policy": copy.deepcopy(EDITORIAL_POLICY),
                    "limitations": ["采用素材原句与有限连接短语白名单，不能验证任意自然语言同义改写，可能拦截无害文案。",
                                    "仅检查提供素材内部的一致性，不证明素材本身真实；不分析图片或视频像素。"]},
    }
    validate(result, CHECK)
    return result


TOOL_PARAMETERS = {
    "search_materials": obj({"query": {"type": "string", "minLength": 1},
                             "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, required=["query"]),
    "estimate_duration": obj({"script": SCRIPT}),
    "check_rules": obj({"script": SCRIPT}),
}
_DESCRIPTIONS = {
    "search_materials": "按关键词检索当前产品素材。空结果时自行决定改查或请求补充；同时返回事实引用与连接短语政策。",
    "estimate_duration": "按固定规则重新估算脚本时长，目标时长和语速由执行环境固定。超时后可修改脚本再查。",
    "check_rules": "检查品牌规则及事实引用。产品描述须使用素材原句及全部限定，其余文字使用检索返回的政策短语。",
}


def tool_definitions() -> list[dict]:
    return [{"type": "function", "function": {"name": name, "description": _DESCRIPTIONS[name],
              "parameters": copy.deepcopy(parameters)}} for name, parameters in TOOL_PARAMETERS.items()]


class ToolRegistry:
    """Context-bound dispatcher; the caller/model decides subsequent actions."""

    def __init__(self, materials: dict, rules: dict, brief: dict,
                 *, failures: dict[str, int] | None = None):
        validate_assets(materials, rules)
        validate(brief, BRIEF)
        self.materials, self.rules, self.brief = copy.deepcopy((materials, rules, brief))
        self.failures = dict(failures or {})
        for name, count in self.failures.items():
            if name not in TOOL_PARAMETERS:
                raise ValidationError("Cannot inject a failure into an unknown tool")
            validate(count, {"type": "integer", "minimum": 0})

    def call(self, name: str, arguments: dict) -> dict:
        envelope = {"schema_version": 1, "tool": name, "evidence_scope": "business_tool_only"}
        if name not in TOOL_PARAMETERS:
            return {**envelope, "status": "error", "error": {
                "code": "unknown_tool", "message": "工具不在允许列表中", "retryable": False}}
        try:
            validate(arguments, TOOL_PARAMETERS[name])
        except ValidationError as error:
            return {**envelope, "status": "error", "error": {
                "code": "invalid_arguments", "message": str(error), "retryable": False}}
        if self.failures.get(name, 0):
            self.failures[name] -= 1
            return {**envelope, "status": "error", "simulated_failure": True, "error": {
                "code": "injected_failure", "message": "显式测试故障，未执行本次业务工具；没有自动重试", "retryable": True}}
        try:
            product_id = self.brief.get("product_id") or self.rules["product_id"]
            if name == "search_materials":
                result = search_materials(self.materials, product_id=product_id, **arguments)
            elif name == "estimate_duration":
                target = self.brief.get("target_duration_seconds")
                validate(target, POSITIVE, "brief.target_duration_seconds")
                result = estimate_duration(arguments["script"], target)
            else:
                result = check_rules(arguments["script"], self.materials, self.rules, product_id=product_id)
            return {**envelope, "status": "ok", "result": result}
        except ValidationError as error:
            return {**envelope, "status": "error", "error": {
                "code": "invalid_context", "message": str(error), "retryable": False}}
        except Exception as error:
            return {**envelope, "status": "error", "error": {
                "code": "tool_execution_error", "message": f"工具执行失败（{type(error).__name__}）", "retryable": False}}
