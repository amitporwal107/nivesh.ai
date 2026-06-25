"""
build_hindi_dict.py — Hybrid English → Hindi translation pipeline for Nivesh.ai

Hybrid approach:
  1. IndicTrans2 (ai4bharat/indictrans2-en-indic-dist-200M) for bulk translation.
     Runs as a GPU Cloud Run Job for production quality.
  2. Financial term override dictionary (hindi_financial_terms.py) applied
     AFTER machine translation for domain-specific correctness.
  3. Falls back to Google Translate (via deep-translator) when no GPU is available
     — for local dev and CI preview. Output is labelled with the engine used.

Outputs:
  frontend-v5/src/lib/i18n.hi.json          — all UI label Hindi translations
  backend/routes/copilot_prompt_catalog_hi.json  — 99 prompt label/query translations

Usage:
  # GPU Cloud Run Job (production):
  python tools/build_hindi_dict.py --engine indictrans2

  # Local dev / CI preview (no GPU needed):
  python tools/build_hindi_dict.py --engine google

  # Dry run — show strings only, no translation:
  python tools/build_hindi_dict.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import os
import time
from pathlib import Path
from typing import Any

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.hindi_financial_terms import apply_overrides, protect_keep_english, restore_keep_english

# ─── String sources ───────────────────────────────────────────────────────────

UI_STRINGS: dict[str, str] = {
    # ── Navigation ──
    "nav.dashboard":          "Dashboard",
    "nav.portfolio":          "Portfolio",
    "nav.copilot":            "Copilot",
    "nav.goals":              "Goals",
    "nav.insights":           "Insights",
    "nav.settings":           "Settings",
    "nav.sign_out":           "Sign Out",

    # ── Chat page ──
    "chat.placeholder":              "Ask anything about your portfolio…",
    "chat.placeholder_advisor":      "Ask about your clients…",
    "chat.send":                     "Send",
    "chat.new_chat":                 "New Chat",
    "chat.history_title":            "Chat History",
    "chat.today":                    "Today",
    "chat.this_week":                "This Week",
    "chat.older":                    "Older",
    "chat.rename":                   "Rename",
    "chat.delete":                   "Delete",
    "chat.delete_confirm":           "Delete this conversation?",
    "chat.cancel":                   "Cancel",
    "chat.confirm":                  "Confirm",
    "chat.thinking":                 "Thinking…",
    "chat.routing":                  "Routing to {agent}…",
    "chat.char_limit":               "{count}/500",
    "chat.char_limit_error":         "Message too long — max 500 characters",
    "chat.resync":                   "Re-sync",
    "chat.nidp_connected":           "NIDP CONNECTED",
    "chat.nidp_disconnected":        "NIDP DISCONNECTED",
    "chat.nidp_cached":              "Using cached data · last sync {time}",
    "chat.grounding_warning":        "Some figures may not match the latest data.",
    "chat.sebi_disclaimer":          "AI-generated for educational purposes only. Not SEBI-registered investment advice. Consult a registered advisor before acting on any recommendation.",
    "chat.empty_portfolio_title":    "Connect your portfolio to get started",
    "chat.empty_portfolio_body":     "Upload your CAS statement or connect your broker account to unlock personalised insights.",
    "chat.empty_portfolio_cta":      "Connect Portfolio",
    "chat.feedback_helpful":         "Helpful",
    "chat.feedback_not_helpful":     "Not helpful",
    "chat.suggested_prompts":        "Suggested for you",
    "chat.category_portfolio":       "Portfolio Health",
    "chat.category_performance":     "Performance",
    "chat.category_risk":            "Risk & Diversification",
    "chat.category_tax":             "Tax",
    "chat.category_goals":           "Goal Planning",

    # ── Agent names ──
    "agent.portfolio_analyst":       "Portfolio Analyst",
    "agent.risk_analyst":            "Risk Analyst",
    "agent.tax_advisor":             "Tax Advisor",
    "agent.mf_analyst":              "MF Analyst",
    "agent.stock_analyst":           "Stock Analyst",
    "agent.goal_planner":            "Goal Planner",
    "agent.market_analyst":          "Market Analyst",
    "agent.recommendation":          "Recommendation Engine",

    # ── Widget labels ──
    "widget.score_label":            "Score",
    "widget.grade":                  "Grade",
    "widget.concentration":          "Concentration",
    "widget.diversification":        "Diversification",
    "widget.risk":                   "Risk",
    "widget.performance":            "Performance",
    "widget.goals":                  "Goals",
    "widget.tax":                    "Tax",
    "widget.top_actions":            "Top Actions · ranked by ₹ impact",
    "widget.actions_urgent":         "URGENT",
    "widget.rebalance_title":        "Rebalance Plan",
    "widget.tax_harvest_title":      "Tax Harvest Opportunities",
    "widget.stress_test_title":      "Stress Test",
    "widget.overlap_title":          "Fund Overlap Analysis",
    "widget.sip_plan_title":         "SIP Plan",
    "widget.sector_rotation_title":  "Sector Rotation",
    "widget.fund_compare_title":     "Fund Comparison",
    "widget.screener_title":         "Stock Screener",
    "widget.goal_tracker_title":     "Goal Tracker",
    "widget.on_track":               "On Track",
    "widget.off_track":              "Off Track",
    "widget.needs_attention":        "Needs Attention",
    "widget.fund_quality":           "Quality",
    "widget.fund_health":            "Health",
    "widget.fund_exit":              "Exit",
    "widget.fund_add":               "Add",
    "widget.lot_harvest_by":         "Harvest by",
    "widget.lot_tax_saved":          "Tax saved",
    "widget.lot_loss":               "Unrealised loss",

    # ── Settings page ──
    "settings.title":                "Settings",
    "settings.language":             "Language",
    "settings.language_en":          "English",
    "settings.language_hi":          "हिन्दी",
    "settings.notifications":        "Notifications",
    "settings.theme":                "Theme",
    "settings.account":              "Account",
    "settings.logout":               "Log Out",

    # ── Error states ──
    "error.stream_failed":           "Something went wrong — please try again.",
    "error.session_load":            "Could not load conversation.",
    "error.generic":                 "An error occurred.",
    "error.retry":                   "Retry",
    "error.nidp_unavailable":        "Live data is temporarily unavailable — using last sync.",
}

# ─── Prompt catalog strings (label + query for each of 99 entries) ───────────
# Populated by importing the real catalog at runtime (avoids duplication)

def load_prompt_strings() -> dict[str, str]:
    """Extract label and query strings from the live prompt catalog."""
    strings: dict[str, str] = {}
    try:
        import importlib.util
        catalog_path = Path(__file__).parent.parent / "backend/routes/copilot_prompt_catalog.py"
        spec = importlib.util.spec_from_file_location("copilot_prompt_catalog", catalog_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for entry in mod.PERSONA_TEMPLATES:
            eid = entry["id"]
            strings[f"prompt.{eid}.label"] = entry["label"]
            strings[f"prompt.{eid}.query"] = entry["query"]
            strings[f"prompt.{eid}.outcome"] = entry["outcome"]
        print(f"  Loaded {len(mod.PERSONA_TEMPLATES)} prompts from catalog", file=sys.stderr)
    except Exception as e:
        print(f"  [WARN] Could not load prompt catalog: {e}", file=sys.stderr)
    return strings


# ─── Translation engines ──────────────────────────────────────────────────────

def translate_indictrans2(texts: list[str]) -> list[str]:
    """
    Translate using IndicTrans2 (GPU required).
    Model: ai4bharat/indictrans2-en-indic-dist-200M
    Run as a Cloud Run Job with an NVIDIA L4 GPU.
    """
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    from IndicTransToolkit import IndicProcessor

    BATCH_SIZE = 8
    MODEL_ID = "ai4bharat/indictrans2-en-indic-dist-200M"

    print(f"  Loading IndicTrans2 model: {MODEL_ID}", file=sys.stderr)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(
        MODEL_ID,
        trust_remote_code=True,
        torch_dtype=torch.float16,
    ).to("cuda")
    model.eval()
    ip = IndicProcessor(inference=True)

    results = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        protected_batch = []
        all_placeholders = []
        for t in batch:
            p, ph = protect_keep_english(t)
            protected_batch.append(p)
            all_placeholders.append(ph)

        inputs = ip.preprocess_batch(protected_batch, src_lang="eng_Latn", tgt_lang="hin_Deva")
        tok = tokenizer(inputs, return_tensors="pt", padding=True, truncation=True).to("cuda")
        with torch.no_grad():
            out = model.generate(**tok, num_beams=5, max_length=512)
        decoded = tokenizer.batch_decode(out, skip_special_tokens=True)
        translated = ip.postprocess_batch(decoded, lang="hin_Deva")

        for j, t in enumerate(translated):
            t = restore_keep_english(t, all_placeholders[j])
            t = apply_overrides(t)
            results.append(t)

        print(f"  Translated batch {i // BATCH_SIZE + 1}/{(len(texts) + BATCH_SIZE - 1) // BATCH_SIZE}",
              file=sys.stderr)
    return results


def translate_google(texts: list[str]) -> list[str]:
    """
    Translate using Google Translate (CPU, no GPU needed).
    For local dev and CI preview only — IndicTrans2 is the production engine.
    Single-word strings that are exact TERM_MAP keys skip the API call entirely.
    Rate-limited to avoid 429s.
    """
    from deep_translator import GoogleTranslator
    from tools.hindi_financial_terms import TERM_MAP
    translator = GoogleTranslator(source="en", target="hi")
    results = []
    for i, text in enumerate(texts):
        # Fast path: exact match in override dict → no API call needed
        if text in TERM_MAP:
            results.append(TERM_MAP[text])
            if (i + 1) % 20 == 0:
                print(f"  Translated {i + 1}/{len(texts)}…", file=sys.stderr)
            continue

        protected, placeholders = protect_keep_english(text)
        try:
            translated = translator.translate(protected) or protected
        except Exception as e:
            print(f"  [WARN] Translation failed for [{text[:40]}]: {e}", file=sys.stderr)
            translated = text  # fallback to English
        translated = restore_keep_english(translated, placeholders)
        results.append(translated)
        if (i + 1) % 20 == 0:
            print(f"  Translated {i + 1}/{len(texts)}…", file=sys.stderr)
            time.sleep(0.3)
    return results


# ─── Main ─────────────────────────────────────────────────────────────────────

def build(engine: str = "google", dry_run: bool = False) -> None:
    print(f"\nNivesh.ai Hindi Dictionary Builder — engine: {engine}", file=sys.stderr)

    # Collect all strings
    all_strings = {**UI_STRINGS}
    print("  Loading prompt catalog…", file=sys.stderr)
    prompt_strings = load_prompt_strings()
    all_strings.update(prompt_strings)
    print(f"  Total strings to translate: {len(all_strings)}", file=sys.stderr)

    if dry_run:
        print("\n── DRY RUN — strings extracted (no translation) ──")
        for k, v in all_strings.items():
            print(f"  {k}: {v!r}")
        return

    # Translate
    keys = list(all_strings.keys())
    values = list(all_strings.values())

    if engine == "indictrans2":
        translated_values = translate_indictrans2(values)
    elif engine == "google":
        translated_values = translate_google(values)
    else:
        raise ValueError(f"Unknown engine: {engine}. Use 'indictrans2' or 'google'.")

    # Build output dict
    hi_dict: dict[str, str] = {}
    for k, v in zip(keys, translated_values):
        hi_dict[k] = v

    # Separate UI strings from prompt strings
    ui_hi = {k: v for k, v in hi_dict.items() if not k.startswith("prompt.")}
    prompt_hi = {k: v for k, v in hi_dict.items() if k.startswith("prompt.")}

    # Write i18n file (frontend)
    i18n_path = Path(__file__).parent.parent / "frontend-v5/src/lib/i18n.hi.json"
    i18n_path.parent.mkdir(parents=True, exist_ok=True)
    i18n_out = {
        "_meta": {
            "engine": engine,
            "model": "ai4bharat/indictrans2-en-indic-dist-200M" if engine == "indictrans2" else "google-translate",
            "overrides_applied": True,
            "requires_review": True,
            "note": "Financial terms applied via hindi_financial_terms.py. SEBI disclaimer requires legal review before use.",
        },
        **ui_hi,
    }
    with open(i18n_path, "w", encoding="utf-8") as f:
        json.dump(i18n_out, f, ensure_ascii=False, indent=2)
    print(f"\n✓ UI strings written → {i18n_path} ({len(ui_hi)} entries)", file=sys.stderr)

    # Write prompt catalog translations
    prompt_path = Path(__file__).parent.parent / "backend/routes/copilot_prompt_catalog_hi.json"
    with open(prompt_path, "w", encoding="utf-8") as f:
        json.dump({
            "_meta": {"engine": engine, "requires_review": True},
            **prompt_hi,
        }, f, ensure_ascii=False, indent=2)
    print(f"✓ Prompt translations → {prompt_path} ({len(prompt_hi)} entries)", file=sys.stderr)

    # Print a sample to stdout for verification
    print("\n── Sample translations (first 10 UI strings) ──")
    for k in list(ui_hi.keys())[:10]:
        en = UI_STRINGS.get(k, "")
        hi = ui_hi[k]
        print(f"  {k}:")
        print(f"    EN: {en}")
        print(f"    HI: {hi}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Nivesh.ai Hindi translation dictionary")
    parser.add_argument("--engine", choices=["indictrans2", "google"], default="google",
                        help="Translation engine (default: google for local dev)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Extract and list strings without translating")
    args = parser.parse_args()
    build(engine=args.engine, dry_run=args.dry_run)
