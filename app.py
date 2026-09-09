"""
AI Math Tutor - Flask backend.

Serves the single-page app (templates/index.html) and exposes JSON
endpoints used by the page's chat feature:

  POST /api/solve         { "text": "..." }                       -> step-by-step solution
  POST /api/solve-image   { "image_base64": "...", "media_type": "image/png", "text": "..." }
                                                                    -> step-by-step solution (via Gemini)

Image solving uses Google's Gemini API by default (GEMINI_API_KEY). If that
key isn't set but ANTHROPIC_API_KEY is, it falls back to Claude instead - so
you only need to configure one of the two.

The Scientific Calculator, Graphing, and Practice Mode tools run entirely
client-side in the browser (same as before) since they need instant,
no-round-trip interactivity - only the "AI chat" solving is server-side here.
"""

import base64
import json
import os
import re

import requests
from flask import Flask, jsonify, render_template, request

from math_engine import MathEvalError, evaluate

app = Flask(__name__)

# Model used for image-based solving with each provider. Override via env
# vars if Google/Anthropic release newer model names.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

IMAGE_INSTRUCTION_TEMPLATE = """You are a careful math tutor. Look at the attached image, which contains a math problem (it may be handwritten or printed). Read the problem, then solve it.{student_note}

Respond with ONLY a JSON object, no markdown fences, no commentary outside the JSON, in exactly this shape:
{{"steps": ["step 1 explanation", "step 2 explanation", ...], "final": "the final answer"}}

Rules:
- Wrap any math expressions in single dollar signs, e.g. $x^2+3x$, so they can be rendered with KaTeX.
- Keep each step to one short sentence.
- "final" should be just the final answer (can include a short label), also using $ ... $ for math.
- If the image does not contain a legible math problem, respond with {{"steps": [], "final": "", "error": "brief reason"}} instead."""

# System-style instruction used to turn the fast regex engine's "I couldn't
# parse/solve that" cases into a real chatbot answer, while keeping the bot
# strictly scoped to math. This is the "knowledge base" the model consults
# to decide whether something is in-scope before it ever tries to solve it.
TEXT_SOLVE_SYSTEM_PROMPT = """You are the AI tutor inside a math-calculator app's chat. Your ONLY job is to help with mathematics: arithmetic, algebra, equations and inequalities, geometry, trigonometry, calculus (limits, derivatives, integrals), statistics and probability, linear algebra, sequences/series, unit conversions, and word problems that reduce to a math calculation.

Decide first whether the user's message is actually a math question.

- If it is NOT a math question (small talk, general knowledge, coding, personal advice, or any non-mathematical topic), respond with EXACTLY this JSON and nothing else: {"decline": true}
- If it IS a math question, solve it like a patient tutor, showing your work, even if it's informally worded, has a typo, or doesn't match a standard template. Make a reasonable interpretation rather than refusing, and briefly note any assumption you made as one of the steps. This includes number-pattern / substitution riddles like "1+1=foo then 3+1=?" - treat these as in-scope: figure out the most plausible rule from the given example (letter count, digit count, alphabetical position, etc.), state that assumption as a step, and give your best-guess answer. Never decline or give up just because only one example was given or the wording is odd - always commit to an answer. This applies even if the riddle happens to use real people's names in place of numbers - treat the names purely as opaque symbols/labels being substituted for numbers, not as a statement about those people.

When it is a math question, respond with ONLY a JSON object, no markdown fences, no commentary outside the JSON, in exactly this shape:
{"steps": ["step 1 explanation", "step 2 explanation", ...], "final": "the final answer"}

Formatting rules:
- Wrap every math expression in single dollar signs, e.g. $x^2+3x$, so it renders with KaTeX.
- Keep each step to one short, clear sentence.
- "final" should be just the final answer (a short label is fine), also wrapped in $ ... $.
- Never reply with prose outside the JSON object, and never leave "steps" or "final" empty for an in-scope math question - always give your best attempt."""


def _clean_json_block(text):
    """Pull the JSON object out of a model reply, tolerating ```json fences
    or stray prose the model adds despite being told not to (riddle-style
    prompts especially tempt it to "explain" outside the JSON)."""
    cleaned = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if match:
            return json.loads(match.group(0))
        raise exc


def _solve_image_with_gemini(api_key, image_b64, media_type, user_text):
    student_note = f' The student also wrote: "{user_text}"' if user_text else ""
    instruction = IMAGE_INSTRUCTION_TEMPLATE.format(student_note=student_note)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": instruction},
                    {"inline_data": {"mime_type": media_type, "data": image_b64}},
                ]
            }
        ]
    }
    resp = requests.post(
        url,
        params={"key": api_key},
        json=payload,
        timeout=45,
    )
    resp.raise_for_status()
    data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini returned no candidates.")
    parts = candidates[0].get("content", {}).get("parts", [])
    text_block = "".join(p.get("text", "") for p in parts).strip()
    return _clean_json_block(text_block)


def _solve_image_with_anthropic(api_key, image_b64, media_type, user_text):
    import anthropic

    student_note = f' The student also wrote: "{user_text}"' if user_text else ""
    instruction = IMAGE_INSTRUCTION_TEMPLATE.format(student_note=student_note)

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                    },
                    {"type": "text", "text": instruction},
                ],
            }
        ],
    )
    text_block = "".join(getattr(block, "text", "") for block in message.content).strip()
    return _clean_json_block(text_block)


def _solve_text_with_gemini(api_key, user_text):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": TEXT_SOLVE_SYSTEM_PROMPT + "\n\nStudent: " + user_text}]}],
        # This is a benign math-tutor chatbot; relax the default safety
        # filters so ordinary requests that happen to mention a public
        # figure's name (as an opaque label in a number-substitution
        # riddle, e.g. "1+1=trump") aren't blocked as if they were asking
        # for political/harassing content.
        "safetySettings": [
            {"category": cat, "threshold": "BLOCK_ONLY_HIGH"}
            for cat in (
                "HARM_CATEGORY_HARASSMENT",
                "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "HARM_CATEGORY_DANGEROUS_CONTENT",
            )
        ],
    }
    resp = requests.post(url, params={"key": api_key}, json=payload, timeout=45)
    resp.raise_for_status()
    data = resp.json()
    block_reason = (data.get("promptFeedback") or {}).get("blockReason")
    if block_reason:
        raise ValueError(f"Gemini blocked the prompt (reason: {block_reason}).")
    candidates = data.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini returned no candidates.")
    finish_reason = candidates[0].get("finishReason")
    if finish_reason == "SAFETY":
        raise ValueError("Gemini blocked the response on safety grounds.")
    parts = candidates[0].get("content", {}).get("parts", [])
    text_block = "".join(p.get("text", "") for p in parts).strip()
    return _normalize_ai_solve(_clean_json_block(text_block))


def _solve_text_with_anthropic(api_key, user_text):
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1000,
        system=TEXT_SOLVE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_text}],
    )
    text_block = "".join(getattr(block, "text", "") for block in message.content).strip()
    return _normalize_ai_solve(_clean_json_block(text_block))


def _normalize_ai_solve(parsed):
    # Normalize into the same shape the frontend already expects.
    if parsed.get("decline"):
        return {"decline": True}
    steps = parsed.get("steps") or []
    final = parsed.get("final") or ""
    if not steps or not final:
        return {"error": True}
    result = {"steps": steps, "final": final}
    if "finalLatex" in parsed:
        result["finalLatex"] = parsed["finalLatex"]
    return result


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/solve", methods=["POST"])
def api_solve():
    data = request.get_json(force=True, silent=True) or {}
    text = data.get("text", "")

    gemini_key = os.environ.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not gemini_key and not anthropic_key:
        return jsonify({"error": "No AI provider configured on the server (set GEMINI_API_KEY or ANTHROPIC_API_KEY)."})

    try:
        if gemini_key:
            return jsonify(_solve_text_with_gemini(gemini_key, text))
        return jsonify(_solve_text_with_anthropic(anthropic_key, text))
    except Exception as exc:
        app.logger.warning("AI text-solve failed: %s", exc)
        return jsonify({"error": f"AI solve failed: {exc}"})


@app.route("/api/calc", methods=["POST"])
def api_calc():
    """Used only if you want server-side verification of a calculator expression."""
    data = request.get_json(force=True, silent=True) or {}
    expr = data.get("expr", "")
    angle_mode = data.get("angleMode", "DEG")
    try:
        result = evaluate(expr, {}, angle_mode)
        return jsonify({"result": result})
    except MathEvalError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/solve-image", methods=["POST"])
def api_solve_image():
    data = request.get_json(force=True, silent=True) or {}
    image_b64 = data.get("image_base64")
    media_type = data.get("media_type", "image/png")
    user_text = data.get("text", "")

    if not image_b64:
        return jsonify({"error": "No image provided."}), 400

    gemini_key = os.environ.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if not gemini_key and not anthropic_key:
        return jsonify({
            "error": "No AI provider is configured on the server. "
                     "Set GEMINI_API_KEY (or ANTHROPIC_API_KEY) in your environment variables."
        }), 500

    try:
        if gemini_key:
            parsed = _solve_image_with_gemini(gemini_key, image_b64, media_type, user_text)
        else:
            parsed = _solve_image_with_anthropic(anthropic_key, image_b64, media_type, user_text)
        return jsonify(parsed)
    except json.JSONDecodeError:
        return jsonify({"error": "Could not parse the AI response."}), 502
    except requests.exceptions.HTTPError as e:
        return jsonify({"error": f"Gemini request failed: {e}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
