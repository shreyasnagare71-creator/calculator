"""
AI Math Tutor - Flask backend.

Serves the single-page app (templates/index.html) and exposes two JSON
endpoints used by the page's chat feature:

  POST /api/solve         { "text": "..." }                       -> step-by-step solution
  POST /api/solve-image   { "image_base64": "...", "media_type": "image/png", "text": "..." }
                                                                    -> step-by-step solution (via Claude)

The Scientific Calculator, Graphing, and Practice Mode tools run entirely
client-side in the browser (same as before) since they need instant,
no-round-trip interactivity - only the "AI chat" solving is server-side here.
"""

import json
import os

from flask import Flask, jsonify, render_template, request

from math_engine import MathEvalError, evaluate, solve_math

app = Flask(__name__)

# Model used for image-based solving. See your Anthropic Console / docs for
# the current list of available model strings.
IMAGE_SOLVE_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")


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

    try:
        import anthropic
    except ImportError:
        return jsonify({
            "error": 'The "anthropic" package is not installed on the server. '
                     "Run: pip install anthropic"
        }), 500

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY is not set on the server."}), 500

    client = anthropic.Anthropic(api_key=api_key)

    student_note = f' The student also wrote: "{user_text}"' if user_text else ""
    instruction = f"""You are a careful math tutor. Look at the attached image, which contains a math problem (it may be handwritten or printed). Read the problem, then solve it.{student_note}

Respond with ONLY a JSON object, no markdown fences, no commentary outside the JSON, in exactly this shape:
{{"steps": ["step 1 explanation", "step 2 explanation", ...], "final": "the final answer"}}

Rules:
- Wrap any math expressions in single dollar signs, e.g. $x^2+3x$, so they can be rendered with KaTeX.
- Keep each step to one short sentence.
- "final" should be just the final answer (can include a short label), also using $ ... $ for math.
- If the image does not contain a legible math problem, respond with {{"steps": [], "final": "", "error": "brief reason"}} instead."""

    try:
        message = client.messages.create(
            model=IMAGE_SOLVE_MODEL,
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
        cleaned = text_block.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned)
        return jsonify(parsed)
    except json.JSONDecodeError:
        return jsonify({"error": "Could not parse the AI response."}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
