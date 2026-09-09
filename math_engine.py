"""
Safe math expression evaluator + step-by-step solver.

This is a Python port of the JavaScript engine used in the browser version
of AI Math Tutor. It deliberately avoids eval()/exec() - expressions are
tokenized and parsed by hand, so nothing but arithmetic on numbers can ever
run here.
"""

import math
import re


class MathEvalError(Exception):
    """Raised for any problem parsing or evaluating an expression."""
    pass


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

def tokenize(s):
    s = re.sub(r'\s+', '', s)
    tokens = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c.isdigit() or c == '.':
            j = i
            while j < n and (s[j].isdigit() or s[j] == '.'):
                j += 1
            tokens.append(('num', float(s[i:j])))
            i = j
        elif c.isalpha():
            j = i
            while j < n and s[j].isalpha():
                j += 1
            tokens.append(('ident', s[i:j].lower()))
            i = j
        elif c in '+-*/^(),%':
            tokens.append(('op', c))
            i += 1
        else:
            raise MathEvalError(f'Unexpected character "{c}"')
    return tokens


CONSTS = {'pi': math.pi, 'e': math.e}


def _make_funcs(angle_mode):
    def to_rad(x):
        return x * math.pi / 180 if angle_mode == 'DEG' else x

    def from_rad(x):
        return x * 180 / math.pi if angle_mode == 'DEG' else x

    return {
        'sin': lambda x: math.sin(to_rad(x)),
        'cos': lambda x: math.cos(to_rad(x)),
        'tan': lambda x: math.tan(to_rad(x)),
        'asin': lambda x: from_rad(math.asin(x)),
        'acos': lambda x: from_rad(math.acos(x)),
        'atan': lambda x: from_rad(math.atan(x)),
        'sqrt': math.sqrt,
        'abs': abs,
        'exp': math.exp,
        'log': math.log10,
        'ln': math.log,
    }


class Parser:
    """Recursive-descent parser/evaluator over a fixed token list."""

    def __init__(self, tokens, scope, funcs):
        self.tokens = tokens
        self.pos = 0
        self.scope = scope or {}
        self.funcs = funcs

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect_end(self):
        if self.pos < len(self.tokens):
            raise MathEvalError('Unexpected trailing input')

    def parse_expression(self):
        val = self.parse_term()
        while self.peek() and self.peek()[0] == 'op' and self.peek()[1] in ('+', '-'):
            op = self.next()[1]
            rhs = self.parse_term()
            val = val + rhs if op == '+' else val - rhs
        return val

    def parse_term(self):
        val = self.parse_implicit()
        while self.peek() and self.peek()[0] == 'op' and self.peek()[1] in ('*', '/', '%'):
            op = self.next()[1]
            rhs = self.parse_implicit()
            if op == '*':
                val = val * rhs
            elif op == '/':
                val = val / rhs
            else:
                val = math.fmod(val, rhs)
        return val

    def parse_implicit(self):
        # supports implicit multiplication like 2x, 2(x+1), 2pi
        val = self.parse_power()
        while self.peek() and (self.peek()[0] == 'ident' or (self.peek()[0] == 'op' and self.peek()[1] == '(')):
            rhs = self.parse_power()
            val = val * rhs
        return val

    def parse_power(self):
        base = self.parse_unary()
        if self.peek() and self.peek()[0] == 'op' and self.peek()[1] == '^':
            self.next()
            exp = self.parse_power()
            return math.pow(base, exp)
        return base

    def parse_unary(self):
        if self.peek() and self.peek()[0] == 'op' and self.peek()[1] == '-':
            self.next()
            return -self.parse_unary()
        if self.peek() and self.peek()[0] == 'op' and self.peek()[1] == '+':
            self.next()
            return self.parse_unary()
        return self.parse_primary()

    def parse_primary(self):
        tok = self.peek()
        if tok is None:
            raise MathEvalError('Unexpected end of expression')
        if tok[0] == 'num':
            self.next()
            return tok[1]
        if tok[0] == 'op' and tok[1] == '(':
            self.next()
            val = self.parse_expression()
            if not (self.peek() and self.peek()[0] == 'op' and self.peek()[1] == ')'):
                raise MathEvalError('Missing closing parenthesis')
            self.next()
            return val
        if tok[0] == 'ident':
            self.next()
            name = tok[1]
            if self.peek() and self.peek()[0] == 'op' and self.peek()[1] == '(':
                if name not in self.funcs:
                    raise MathEvalError(f'Unknown function "{name}"')
                self.next()
                arg = self.parse_expression()
                if not (self.peek() and self.peek()[0] == 'op' and self.peek()[1] == ')'):
                    raise MathEvalError('Missing closing parenthesis')
                self.next()
                return self.funcs[name](arg)
            if name == 'x':
                if 'x' not in self.scope:
                    raise MathEvalError('x is not defined')
                return self.scope['x']
            if name in CONSTS:
                return CONSTS[name]
            raise MathEvalError(f'Unknown identifier "{name}"')
        raise MathEvalError('Unexpected token')


def evaluate(expr, scope=None, angle_mode='DEG'):
    """Evaluate a math expression string. scope may supply {'x': value}."""
    tokens = tokenize(expr)
    if not tokens:
        raise MathEvalError('Empty expression')
    funcs = _make_funcs(angle_mode)
    parser = Parser(tokens, scope, funcs)
    val = parser.parse_expression()
    parser.expect_end()
    return val


# ---------------------------------------------------------------------------
# Helpers shared by the step-by-step solver
# ---------------------------------------------------------------------------

def round_(n):
    return round(n, 6)


def fmt(n):
    """Render a number the way JS template literals would (no trailing .0)."""
    if isinstance(n, float):
        if n.is_integer():
            return str(int(n))
        return repr(round(n, 6)).rstrip('0').rstrip('.') if '.' in repr(round(n, 6)) else repr(n)
    return str(n)


def normalize(text):
    return (text.replace('\u00d7', '*')
                .replace('\u00f7', '/')
                .replace('\u2212', '-')
                .replace('\u00b2', '^2')
                .replace('\u00b3', '^3')
                .strip())


def parse_poly_terms(expr):
    expr = re.sub(r'\s+', '', expr)
    if not re.match(r'^[+-]', expr):
        expr = '+' + expr
    term_re = re.compile(r'([+-])(\d*\.?\d*)(x(\^(\d+))?)?')
    terms = []
    for m in term_re.finditer(expr):
        sign_s, coef_s, xpart, _pow_group, power_s = m.groups()
        if coef_s == '' and not xpart:
            continue
        sign = -1 if sign_s == '-' else 1
        has_x = bool(xpart)
        power = int(power_s) if (has_x and power_s) else (1 if has_x else 0)
        coef = 1.0 if coef_s == '' else float(coef_s)
        coef *= sign
        terms.append({'coef': coef, 'power': power})
    return terms


def format_poly_latex(terms):
    terms = [t for t in terms if t['coef'] != 0]
    terms.sort(key=lambda t: -t['power'])
    if not terms:
        return '0'
    parts = []
    for i, t in enumerate(terms):
        abs_c = abs(t['coef'])
        sign = '-' if t['coef'] < 0 else ('' if i == 0 else '+')
        spaced = sign if i == 0 else f' {sign} '
        coef_str = '' if (abs_c == 1 and t['power'] != 0) else fmt(abs_c)
        var_str = '' if t['power'] == 0 else ('x' if t['power'] == 1 else f'x^{{{t["power"]}}}')
        parts.append(f'{spaced}{coef_str}{var_str}')
    return ''.join(parts)


# ---------------------------------------------------------------------------
# Step-by-step solver (mirrors the browser demo's routing logic)
# ---------------------------------------------------------------------------

def solve_math(raw):
    text = normalize((raw or '').strip())
    lower = text.lower()

    # --- quadratic: ax^2 + bx + c = 0 ---------------------------------
    quad = re.search(r'([+-]?\d*)x\^2\s*([+-]\s*\d+)?x?\s*([+-]\s*\d+)?\s*=\s*0', text, re.I)
    if quad and 'x^2' in lower:
        a_s, b_s, c_s = quad.groups()
        a = 1 if a_s in ('', '+') else (-1 if a_s == '-' else float(a_s))
        b = float(b_s.replace(' ', '')) if b_s else 0
        c = float(c_s.replace(' ', '')) if c_s else 0
        disc = b * b - 4 * a * c
        steps = [
            f'This is a quadratic in the form $ax^2+bx+c=0$, with $a={fmt(a)}$, $b={fmt(b)}$, $c={fmt(c)}$.',
            f'Compute the discriminant: $D=b^2-4ac=({fmt(b)})^2-4({fmt(a)})({fmt(c)})={fmt(disc)}$.',
        ]
        if disc > 0:
            r1 = round_((-b + math.sqrt(disc)) / (2 * a))
            r2 = round_((-b - math.sqrt(disc)) / (2 * a))
            steps.append('Since $D>0$, use $x=\\dfrac{-b\\pm\\sqrt{D}}{2a}$ to get two real roots.')
            final_latex = f'x={fmt(r1)} \\text{{ or }} x={fmt(r2)}'
        elif disc == 0:
            r = round_(-b / (2 * a))
            steps.append('Since $D=0$, there is one repeated real root.')
            final_latex = f'x={fmt(r)}'
        else:
            re_part = round_(-b / (2 * a))
            im_part = round_(math.sqrt(-disc) / (2 * a))
            steps.append('Since $D<0$, the roots are complex.')
            final_latex = f'x={fmt(re_part)}\\pm {fmt(im_part)}i'
        return {'steps': steps, 'final': f'${final_latex}$', 'finalLatex': final_latex}

    # --- linear: ax + b = c --------------------------------------------
    linear = re.search(r'([+-]?\d*)x\s*([+-]\s*\d+)?\s*=\s*([+-]?\d+)', text, re.I)
    if linear and 'x' in lower and 'x^2' not in lower:
        a_s, b_s, rhs_s = linear.groups()
        a = 1 if a_s in ('', '+') else (-1 if a_s == '-' else float(a_s))
        b = float(b_s.replace(' ', '')) if b_s else 0
        rhs = float(rhs_s)
        x = round_((rhs - b) / a)
        steps = [
            f'Isolate the $x$ term: ${fmt(a)}x={fmt(rhs)}-({fmt(b)})={fmt(rhs - b)}$.',
            f'Divide both sides by {fmt(a)}: $x=\\dfrac{{{fmt(rhs - b)}}}{{{fmt(a)}}}$.',
        ]
        return {'steps': steps, 'final': f'$x={fmt(x)}$', 'finalLatex': f'x={fmt(x)}'}

    # --- differentiation of a polynomial ---------------------------------
    if 'differentiate' in lower or 'derivative' in lower:
        expr_part = re.sub(r'.*(differentiate|derivative of)', '', text, flags=re.I).strip()
        terms = parse_poly_terms(expr_part)
        diff_terms = [{'coef': t['coef'] * t['power'], 'power': t['power'] - 1} for t in terms if t['power'] > 0]
        steps = []
        for t in terms:
            if t['power'] == 0:
                steps.append(f'The constant term ${fmt(t["coef"])}$ differentiates to $0$.')
            else:
                coef_disp = '' if t['coef'] == 1 else fmt(t['coef'])
                pow_disp = '' if t['power'] == 1 else f'^{{{t["power"]}}}'
                new_coef = fmt(t['coef'] * t['power'])
                new_pow = t['power'] - 1
                new_pow_disp = '' if new_pow in (0, 1) else f'^{{{new_pow}}}'
                steps.append(f'$\\dfrac{{d}}{{dx}}({coef_disp}x{pow_disp}) = {new_coef}x{new_pow_disp}$')
        fl = format_poly_latex(diff_terms)
        return {'steps': steps, 'final': f"$f'(x)={fl}$", 'finalLatex': f"f'(x)={fl}"}

    # --- integration of a polynomial --------------------------------------
    if 'integrate' in lower or 'integral of' in lower:
        expr_part = re.sub(r'.*(integrate|integral of)', '', text, flags=re.I).strip()
        terms = parse_poly_terms(expr_part)
        int_terms = [{'coef': t['coef'] / (t['power'] + 1), 'power': t['power'] + 1} for t in terms]
        steps = []
        for t in terms:
            np_ = t['power'] + 1
            coef_disp = '' if t['coef'] == 1 else fmt(t['coef'])
            pow_disp = '' if t['power'] == 0 else ('' if t['power'] == 1 else f'^{{{t["power"]}}}')
            steps.append(f'$\\displaystyle\\int {coef_disp}x{pow_disp}\\,dx = {fmt(round_(t["coef"] / np_))}x^{{{np_}}}$')
        fl = format_poly_latex(int_terms)
        return {'steps': steps, 'final': f'${fl} + C$', 'finalLatex': f'{fl} + C'}

    # --- percentage --------------------------------------------------------
    pct = re.search(r'(\d+(\.\d+)?)\s*%\s*of\s*(\d+(\.\d+)?)', text, re.I)
    if pct:
        p = float(pct.group(1))
        n = float(pct.group(3))
        result = round_((p / 100) * n)
        steps = [
            f'Convert the percentage to a decimal: ${fmt(p)}\\% = \\dfrac{{{fmt(p)}}}{{100}} = {fmt(p / 100)}$.',
            f'Multiply by the number: ${fmt(p / 100)} \\times {fmt(n)} = {fmt(result)}$.',
        ]
        return {'steps': steps, 'final': f'${fmt(result)}$', 'finalLatex': fmt(result)}

    # --- square root ---------------------------------------------------------
    sqrt_m = re.search(r'square root of\s*(\d+(\.\d+)?)|sqrt\(?\s*(\d+(\.\d+)?)\)?', text, re.I)
    if sqrt_m:
        n = float(sqrt_m.group(1) or sqrt_m.group(3))
        result = round_(math.sqrt(n))
        steps = [f'Find a number which, multiplied by itself, gives ${fmt(n)}$.']
        return {
            'steps': steps,
            'final': f'$\\sqrt{{{fmt(n)}}} = {fmt(result)}$',
            'finalLatex': f'\\sqrt{{{fmt(n)}}} = {fmt(result)}',
        }

    # --- circle area -----------------------------------------------------
    circle = re.search(r'area of.*circle.*radius\s*(\d+(\.\d+)?)', lower) or \
        re.search(r'circle.*radius\s*(\d+(\.\d+)?).*area', lower)
    if circle:
        r = float(circle.group(1))
        area = round_(math.pi * r * r)
        steps = [
            'Use the formula for the area of a circle: $A=\\pi r^2$.',
            f'Substitute $r={fmt(r)}$: $A=\\pi\\times {fmt(r)}^2=\\pi\\times {fmt(r * r)}$.',
        ]
        return {
            'steps': steps,
            'final': f'$A \\approx {fmt(area)}\\text{{ cm}}^2$',
            'finalLatex': f'A \\approx {fmt(area)} cm^2',
        }

    # --- plain arithmetic fallback ("What is 25 x 40?", "12 * 3", ...) ----
    cleaned_for_engine = re.sub(r'what is|calculate|find|\?', '', text, flags=re.I).strip()
    # A lowercase "x" between two numbers is a multiplication sign here
    # ("25 x 40"), not the algebra variable - this path never solves for x.
    arithmetic_expr = re.sub(r'(\d)\s*x\s*(?=\d)', r'\1*', cleaned_for_engine, flags=re.I)
    if re.match(r'^[\d+\-*/^().\spie]+$', arithmetic_expr, re.I) and re.search(r'\d', arithmetic_expr):
        try:
            result = evaluate(arithmetic_expr.replace(' ', ''), {})
            if isinstance(result, (int, float)) and math.isfinite(result):
                display_expr = arithmetic_expr.strip().replace('*', '\\times ')
                return {
                    'steps': [f'Evaluate the expression: ${display_expr}$'],
                    'final': f'${fmt(round_(result))}$',
                    'finalLatex': fmt(round_(result)),
                }
        except MathEvalError:
            pass

    math_hints = re.search(
        r'[0-9]|solve|calculate|differentiate|integrate|area|radius|sqrt|square root|percent|%|equation|x\^|derivative',
        lower,
    )
    if not math_hints:
        return {'decline': True}
    return {'error': True}
