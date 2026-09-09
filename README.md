# AI Math Tutor — Python (Flask) version

A Flask backend serving the same AI Math Tutor interface (chat, Scientific
Calculator, Graphing, Practice Mode, Saved Solutions, chat history) that was
previously a static HTML/JS page.

## What's Python vs. what's still JavaScript

- **Python (server-side):** the step-by-step math solver used by the chat
  (`math_engine.py`), and the endpoint that sends a photo of a problem to
  Claude to be read and solved (`app.py`).
- **JavaScript (client-side, unchanged):** the Scientific Calculator,
  Graphing tool, Practice Mode, Saved Solutions, and chat history/UI — these
  stay in the browser because they need instant, no-round-trip interaction
  (e.g. dragging to pan a graph).

## Project layout

```
math_tutor_python/
├── app.py              Flask app: routes + the /api/solve-image call to Claude
├── math_engine.py       Safe expression evaluator + step-by-step solver (pure Python, no eval())
├── templates/
│   └── index.html       The full UI (HTML/CSS/JS), calling the Flask API for chat solving
├── requirements.txt
└── README.md
```

## Setup

```bash
cd math_tutor_python
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Running

```bash
python app.py
```

Then open **http://127.0.0.1:5000** in your browser.

## Enabling "solve from a photo"

The photo-solving feature calls the Anthropic API from the server, so it
needs an API key:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # Windows: set ANTHROPIC_API_KEY=sk-ant-...
python app.py
```

Without the key set, the text-based chat solver, calculator, graphing, and
practice mode all still work fully — only the "attach/paste a photo" path in
the chat will return an error until a key is configured.

You can also override the model used for photo-solving:

```bash
export ANTHROPIC_MODEL="claude-sonnet-5"
```

## API endpoints

| Method | Path              | Body                                                   | Returns |
|--------|-------------------|---------------------------------------------------------|---------|
| POST   | `/api/solve`       | `{"text": "Solve x^2 - 5x + 6 = 0"}`                    | `{"steps": [...], "final": "...", "finalLatex": "..."}` (or `{"decline": true}` / `{"error": true}`) |
| POST   | `/api/solve-image` | `{"image_base64": "...", "media_type": "image/png", "text": "optional note"}` | same shape as above, via Claude |
| POST   | `/api/calc`        | `{"expr": "2*(3+4)^2", "angleMode": "DEG"}`             | `{"result": 98}` (server-side expression check; the calculator UI evaluates client-side already) |

## Notes

- `math_engine.py` never calls `eval()`/`exec()` — it's a hand-written
  tokenizer/parser, so nothing beyond arithmetic on numbers can run there.
- This is a development server (`app.run(debug=True)`). For production, run
  it behind a real WSGI server (e.g. `gunicorn app:app`) and turn debug mode
  off.
