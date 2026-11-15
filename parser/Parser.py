# parser/parser.py
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from parser.cfg import (
    NULL,
    START_SYMBOL,
    NON_TERMINALS,
    TERMINALS,
    PRODUCTIONS_BY_ID,
    PRODUCTIONS_BY_LHS,
    Production,
)
from parser.grammar_sets import PREDICT_SET

EOF_SYMBOL = "$"


@dataclass
class ParseStep:
    step_num: int
    stack_top: str
    lookahead: str
    action: str
    rule_id: Optional[int] = None


@dataclass
class ParseResult:
    valid: bool
    steps: List[ParseStep] = field(default_factory=list)
    error: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None


def normalize_token(token: Any) -> str:
    """Map a lexer token object, tuple, or string to a CFG terminal symbol."""
    if isinstance(token, str):
        return token

    if hasattr(token, "kind"):
        kind = token.kind
        lexeme = getattr(token, "lexeme", "")
    elif hasattr(token, "type"):
        kind = token.type
        lexeme = getattr(token, "value", getattr(token, "lexeme", ""))
    elif isinstance(token, tuple) and token:
        kind = token[0]
        lexeme = token[1] if len(token) > 1 else ""
    else:
        return str(token)

    if kind == "EOF" or kind == EOF_SYMBOL:
        return EOF_SYMBOL

    symbol_map = {
        "LPAREN": "(",
        "RPAREN": ")",
        "LBRACE": "{",
        "RBRACE": "}",
        "LBRACKET": "[",
        "RBRACKET": "]",
        "SEMICOLON": ";",
        "COMMA": ",",
        "COLON": ":",
        "DOT": ".",
        "TILDE": "~",
        "NOT": "!",
        "PLUS": "+",
        "MINUS": "-",
        "STAR": "*",
        "SLASH": "/",
        "PERCENT": "%",
        "ASSIGN": "=",
        "LT": "<",
        "LTE": "<=",
        "GT": ">",
        "GTE": ">=",
        "EQ": "==",
        "NEQ": "!=",
        "AND": "&&",
        "OR": "||",
        "INC": "++",
        "DEC": "--",
        "PLUS_ASSIGN": "+=",
        "MINUS_ASSIGN": "-=",
        "MUL_ASSIGN": "*=",
        "DIV_ASSIGN": "/=",
        "MOD_ASSIGN": "%=",
    }

    if kind in symbol_map and symbol_map[kind] in TERMINALS:
        return symbol_map[kind]
    if kind in TERMINALS:
        return kind
    if lexeme in TERMINALS:
        return lexeme
    return str(kind).lower()


def _extract_position(token: Any) -> Tuple[Optional[int], Optional[int]]:
    if hasattr(token, "line") or hasattr(token, "column"):
        return getattr(token, "line", None), getattr(token, "column", None)
    if isinstance(token, tuple) and len(token) >= 3:
        return token[-2], token[-1]
    return None, None


class LL1Parser:
    def __init__(self) -> None:
        self.parse_table: Dict[Tuple[str, str], int] = {}
        self.conflicts: List[Tuple[str, str, int, int]] = []
        self._build_parse_table()

    def _build_parse_table(self) -> None:
        for lhs, prods in PRODUCTIONS_BY_LHS.items():
            for prod in prods:
                for terminal in PREDICT_SET.get(prod.rule_id, set()):
                    key = (lhs, terminal)
                    if key in self.parse_table and self.parse_table[key] != prod.rule_id:
                        self.conflicts.append((lhs, terminal, self.parse_table[key], prod.rule_id))
                    self.parse_table[key] = prod.rule_id

    def parse(self, tokens: List[Any]) -> ParseResult:
        if self.conflicts:
            lhs, tok, r1, r2 = self.conflicts[0]
            return ParseResult(
                valid=False,
                error=f"LL(1) conflict on {lhs} for '{tok}': R{r1} vs R{r2}",
            )

        filtered = []
        for tok in tokens:
            kind = getattr(tok, "kind", None) or getattr(tok, "type", None)
            if isinstance(tok, tuple) and tok:
                kind = tok[0]
            if kind in {"NEWLINE", "WHITESPACE", "COMMENT"}:
                continue
            filtered.append(tok)

        if not filtered or normalize_token(filtered[-1]) != EOF_SYMBOL:
            filtered.append(("EOF", "", None, None))

        stack: List[str] = [EOF_SYMBOL, START_SYMBOL]
        idx = 0
        steps: List[ParseStep] = []
        step_num = 1

        while stack:
            top = stack.pop()
            curr_tok = filtered[idx]
            lookahead = normalize_token(curr_tok)
            line, col = _extract_position(curr_tok)

            if top == EOF_SYMBOL and lookahead == EOF_SYMBOL:
                steps.append(ParseStep(step_num, top, lookahead, "ACCEPT"))
                return ParseResult(valid=True, steps=steps)

            if top in TERMINALS or top == EOF_SYMBOL:
                if top == lookahead:
                    steps.append(ParseStep(step_num, top, lookahead, f"MATCH '{lookahead}'"))
                    idx += 1
                else:
                    expected = sorted(PREDICT_SET.get(self.parse_table.get((stack[-1], lookahead), -1), {top}))
                    return ParseResult(
                        valid=False,
                        steps=steps,
                        error=f"Expected '{top}', got '{lookahead}' (expected one of: {expected})",
                        line=line,
                        column=col,
                    )
            elif top in NON_TERMINALS:
                rule_id = self.parse_table.get((top, lookahead))
                if rule_id is None:
                    expected = sorted(
                        tok for (nt, tok) in self.parse_table.keys() if nt == top
                    )
                    return ParseResult(
                        valid=False,
                        steps=steps,
                        error=f"Unexpected '{lookahead}' for {top}. Expected: {expected}",
                        line=line,
                        column=col,
                    )

                prod: Production = PRODUCTIONS_BY_ID[rule_id]
                rhs_display = " ".join(prod.rhs)
                steps.append(
                    ParseStep(
                        step_num=step_num,
                        stack_top=top,
                        lookahead=lookahead,
                        action=f"EXPAND R{prod.rule_id}: {prod.lhs} -> {rhs_display}",
                        rule_id=prod.rule_id,
                    )
                )

                if prod.rhs != (NULL,):
                    for sym in reversed(prod.rhs):
                        stack.append(sym)
            else:
                return ParseResult(
                    valid=False,
                    steps=steps,
                    error=f"Unknown symbol '{top}' on stack",
                    line=line,
                    column=col,
                )

            step_num += 1

        return ParseResult(valid=False, steps=steps, error="Parse stack emptied prematurely")

    IGNORED_TOKENS = {"whitespace", "newline", "comment"}
    
    def _token_kind(token: Any) -> str:
        if isinstance(token, str):
            return token
        if hasattr(token, "kind"):
            return token.kind
        if hasattr(token, "type"):
            return token.type
        if isinstance(token, tuple) and token:
            return str(token[0])
        return str(token)
    
    
    def _extract_position(token: Any) -> Tuple[Optional[int], Optional[int]]:
        if hasattr(token, "line"):
            line = getattr(token, "line", None)
            col = getattr(token, "column", None)
            if col is None:
                col = getattr(token, "col", None)
            return line, col
        if isinstance(token, tuple) and len(token) >= 4:
            return token[2], token[3]
        if isinstance(token, tuple) and len(token) >= 3:
            return token[-2], token[-1]
        return None, None