"""Structural ecology evidence, not a biological or habitat compatibility judgement."""
import hashlib
import re
from pathlib import Path


def check(path, *, living=None, reason=None):
    result = {"result": "FAIL", "habitat": "", "traits_with_reason": [], "sha256": None,
              "status": "NOT SET", "review_status": "NOT SET"}
    if living is False or (isinstance(reason, str) and reason.strip()):
        return {**result, "result": "N/A", "reason": reason or "Manifest declares living: false"}
    if not path or not Path(path).is_file():
        return {**result, "reason": "Ecology entry is missing"}
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig")
    result["sha256"] = hashlib.sha256(raw).hexdigest()
    # Ignore commented-out examples; a heading without evidence does not count.
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    front = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|\Z)", text, re.S)
    if front:
        try:
            import yaml
            data = yaml.safe_load(front[1]) or {}
            if not isinstance(data, dict):
                raise ValueError("Ecology front matter must be a mapping")
        except (ImportError, ValueError) as exc:
            return {**result, "result": "UNMEASURED", "reason": str(exc)}
        except yaml.YAMLError as exc:
            return {**result, "reason": "Invalid YAML front matter: " + str(exc)}
        result.update(status=str(data.get("status", "NOT SET")),
                      review_status=str(data.get("review_status", "NOT SET")))
        if data.get("living") is False and living is not True:
            return {**result, "result": "N/A", "reason": "Ecology declares living: false"}
        if data.get("living") is False and living is True:
            return {**result, "reason": "Conflicting living declarations"}
        def content(value):
            return isinstance(value, str) and bool(value.strip()) and not re.fullmatch(
                r"(?:tbd|todo|unknown|none|n/?a|[-.…]+)[.!]?", value.strip(), re.I)
        habitat = data.get("habitat", {})
        habitat = habitat.get("where", "") if isinstance(habitat, dict) else habitat
        traits = data.get("traits", [])
        traits = [f"{t['feature']}: {t['because']}" for t in traits
                  if isinstance(t, dict) and content(t.get("feature")) and content(t.get("because"))] if isinstance(traits, list) else []
        result.update(habitat=habitat.strip() if content(habitat) else "", traits_with_reason=traits)
        # Do not let the YAML source itself masquerade as Markdown evidence.
        text = text[front.end():]
    sections, current = {}, ""
    for line in text.splitlines():
        heading = re.match(r"^#{1,6}\s+(.+)", line)
        if heading:
            current = heading[1].strip().lower()
            sections.setdefault(current, [])
        elif line.strip():
            sections.setdefault(current, []).append(line.strip())
    habitat = result["habitat"] or next(("\n".join(lines) for key, lines in sections.items()
                    if re.search(r"\bhabitat\b", key) and lines), "")
    if not habitat:
        m = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?habitat(?:\*\*)?\s*:\s*(\S.+)$", text)
        habitat = m[1].strip() if m else ""
    trait_lines = [line for key, lines in sections.items()
                   if re.search(r"\b(traits?|adaptations?)\b", key) for line in lines]
    causal = r"\b(because|so that|in order to|reason\s*:|reduces?|retains?|protects?|prevents?|allows?|helps?)\b"
    traits = result["traits_with_reason"] + [line for line in trait_lines if re.search(causal, line, re.I)
              and len(re.findall(r"\w+", line)) >= 5 and not set(line) <= {"|", "-", " ", ":"}]
    # Also support an explicit Trait | Reason Markdown table.
    for i, line in enumerate(trait_lines):
        cells = [s.strip() for s in line.strip("|").split("|")]
        if len(cells) >= 2 and "trait" in cells[0].lower() and "reason" in cells[1].lower():
            for row in trait_lines[i + 2:]:
                values = [s.strip() for s in row.strip("|").split("|")]
                if len(values) >= 2 and all(len(re.findall(r"\w+", s)) >= 2 for s in values[:2]):
                    traits.append(row)
    placeholder = r"^(?:tbd|todo|unknown|none|n/?a|[-.…]+)[.!]?$"
    if re.fullmatch(placeholder, habitat.strip(), re.I):
        habitat = ""
    result.update(habitat=habitat, traits_with_reason=list(dict.fromkeys(traits)))
    result["result"] = "PASS" if habitat and traits else "FAIL"
    result["reason"] = "Habitat and reasoned trait present" if result["result"] == "PASS" else "Needs habitat text and at least one trait with a reason"
    return result
