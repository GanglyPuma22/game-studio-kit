"""Structural ecology evidence, not a biological or habitat compatibility judgement."""
import hashlib
import re
from pathlib import Path


def check(path):
    result = {"result": "FAIL", "habitat": "", "traits_with_reason": [], "sha256": None}
    if not path or not Path(path).is_file():
        return {**result, "reason": "Ecology entry is missing"}
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig")
    result["sha256"] = hashlib.sha256(raw).hexdigest()
    # Ignore commented-out examples; a heading without evidence does not count.
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    sections, current = {}, ""
    for line in text.splitlines():
        heading = re.match(r"^#{1,6}\s+(.+)", line)
        if heading:
            current = heading[1].strip().lower()
            sections.setdefault(current, [])
        elif line.strip():
            sections.setdefault(current, []).append(line.strip())
    habitat = next(("\n".join(lines) for key, lines in sections.items()
                    if re.search(r"\bhabitat\b", key) and lines), "")
    if not habitat:
        m = re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?habitat(?:\*\*)?\s*:\s*(\S.+)$", text)
        habitat = m[1].strip() if m else ""
    trait_lines = [line for key, lines in sections.items()
                   if re.search(r"\b(traits?|adaptations?)\b", key) for line in lines]
    causal = r"\b(because|so that|in order to|reason\s*:|reduces?|retains?|protects?|prevents?|allows?|helps?)\b"
    traits = [line for line in trait_lines if re.search(causal, line, re.I)
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
