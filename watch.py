import json
import os
import re
import urllib.request
from datetime import datetime, timezone

API_URL = "https://openrouter.ai/api/v1/models"
STATE_FILE = "models-state.json"
REPORT_FILE = "report.md"

SUSPICIOUS_WORDS = [
    "alpha",
    "beta",
    "stealth",
    "cloaked",
    "anonymous",
    "testing version",
    "experimental",
]


def fetch_models():
    request = urllib.request.Request(
        API_URL,
        headers={
            "User-Agent": "openrouter-stealth-watcher/1.0"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)

    return data["data"]


def load_state():
    if not os.path.exists(STATE_FILE):
        return None

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(models):
    state = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "models": {
            model["id"]: model
            for model in models
        }
    }

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def is_free(model):
    pricing = model.get("pricing") or {}

    try:
        prompt = float(pricing.get("prompt", -1))
        completion = float(pricing.get("completion", -1))

        return prompt == 0 and completion == 0
    except (ValueError, TypeError):
        return False


def suspicion_reasons(model):
    reasons = []

    model_id = (model.get("id") or "").lower()
    name = (model.get("name") or "").lower()
    description = (model.get("description") or "").lower()

    combined = f"{model_id} {name} {description}"

    if model_id.startswith("stealth/"):
        reasons.append("stealth namespace")

    if model_id.startswith("openrouter/"):
        reasons.append("OpenRouter namespace")

    for word in SUSPICIOUS_WORDS:
        if word in combined:
            reasons.append(f'contains "{word}"')

    if is_free(model):
        reasons.append("free")

    context = model.get("context_length")
    if isinstance(context, int) and context >= 500_000:
        reasons.append(f"large context ({context:,})")

    return list(dict.fromkeys(reasons))


def looks_suspicious(model):
    reasons = suspicion_reasons(model)

    model_id = (model.get("id") or "").lower()
    text = (
        (model.get("id") or "")
        + " "
        + (model.get("name") or "")
        + " "
        + (model.get("description") or "")
    ).lower()

    explicit = (
        model_id.startswith("stealth/")
        or "stealth" in text
        or "cloaked" in text
    )

    alpha_beta = (
        "alpha" in text
        or "beta" in text
    )

    openrouter_candidate = (
        model_id.startswith("openrouter/")
        and alpha_beta
    )

    free_alpha = (
        is_free(model)
        and alpha_beta
    )

    return explicit or openrouter_candidate or free_alpha


def model_summary(model):
    pricing = model.get("pricing") or {}

    prompt = pricing.get("prompt", "?")
    completion = pricing.get("completion", "?")

    context = model.get("context_length")
    context_text = f"{context:,}" if isinstance(context, int) else "unknown"

    reasons = suspicion_reasons(model)

    created = model.get("created")

    if created:
        try:
            created_text = datetime.fromtimestamp(
                created,
                timezone.utc
            ).isoformat()
        except Exception:
            created_text = str(created)
    else:
        created_text = "unknown"

    return f"""
### `{model.get("id")}`

**Name:** {model.get("name", "unknown")}

**Created:** {created_text}

**Context:** {context_text}

**Pricing**
- Prompt: `{prompt}`
- Completion: `{completion}`

**Why flagged:** {", ".join(reasons) if reasons else "none"}

**Description**

{model.get("description", "No description")}
"""


def main():
    models = fetch_models()

    previous_state = load_state()

    # First run: establish baseline only.
    if previous_state is None:
        save_state(models)

        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            f.write("")

        print(f"Baseline created with {len(models)} models.")
        return

    old_models = previous_state.get("models", {})
    new_models = {
        model["id"]: model
        for model in models
    }

    added_ids = sorted(set(new_models) - set(old_models))
    removed_ids = sorted(set(old_models) - set(new_models))

    suspicious_added = [
        new_models[model_id]
        for model_id in added_ids
        if looks_suspicious(new_models[model_id])
    ]

    suspicious_removed = [
        old_models[model_id]
        for model_id in removed_ids
        if looks_suspicious(old_models[model_id])
    ]

    report = []

    if suspicious_added:
        report.append("# 🚨 New suspicious OpenRouter model(s)\n")

        for model in suspicious_added:
            report.append(model_summary(model))

    if suspicious_removed:
        report.append("# ⚠️ Suspicious model(s) disappeared\n")

        for model in suspicious_removed:
            report.append(model_summary(model))

    save_state(models)

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    print(f"Current models: {len(models)}")
    print(f"Added: {len(added_ids)}")
    print(f"Removed: {len(removed_ids)}")
    print(f"Suspicious added: {len(suspicious_added)}")
    print(f"Suspicious removed: {len(suspicious_removed)}")


if __name__ == "__main__":
    main()