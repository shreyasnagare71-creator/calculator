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

import requests
from flask import Flask, jsonify, render_template, request

from math_engine import MathEvalError, evaluate, solve_math

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


def _clean_json_block(text):
    """Strip ```json fences (if any) and parse the JSON object out of a model reply."""
    cleaned = text.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned)


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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/solve", methods=["POST"])
def api_solve():
    data = request.get_json(force=True, silent=True) or {}
    text = data.get("text", "")
    try:
        result = solve_math(text)
    except Exception:
        result = {"error": True}
    return jsonify(result)


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
