"""Derive FIRST, FOLLOW, and PREDICT sets from CFG.py.

Run from this directory with:
    python grammar_sets.py

The module can also be imported by a parser:
    from grammar_sets import GRAMMAR_SETS, FIRST, FOLLOW, PREDICT
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence, Set, Tuple

from .cfg import NULL, START_SYMBOL, PRODUCTIONS, Production

END_MARKER = "$"
SymbolSet = Set[str]


@dataclass(frozen=True)
class GrammarSets:
    """Container for the grammar's derived sets."""

    first: Dict[str, SymbolSet]
    follow: Dict[str, SymbolSet]
    predict: Dict[int, SymbolSet]
    non_terminals: SymbolSet
    terminals: SymbolSet


def _get_non_terminals(productions: Sequence[Production]) -> SymbolSet:
    return {production.lhs for production in productions}


def _validate_grammar(
    productions: Sequence[Production], start_symbol: str, epsilon: str
) -> None:
    """Catch common grammar-definition mistakes before deriving the sets."""
    if not productions:
        raise ValueError("The grammar has no productions.")

    rule_ids = [production.rule_id for production in productions]
    if len(rule_ids) != len(set(rule_ids)):
        raise ValueError("Production rule_id values must be unique.")

    non_terminals = _get_non_terminals(productions)
    if start_symbol not in non_terminals:
        raise ValueError(
            f"Start symbol {start_symbol!r} has no production in the grammar."
        )

    for production in productions:
        if epsilon in production.rhs and production.rhs != (epsilon,):
            raise ValueError(
                f"Rule {production.rule_id} uses epsilon alongside other symbols. "
                "Epsilon must be the only symbol in that production."
            )


def first_of_sequence(
    sequence: Sequence[str],
    first_sets: Mapping[str, SymbolSet],
    non_terminals: SymbolSet,
    epsilon: str = NULL,
) -> SymbolSet:
    """Return FIRST(sequence), including epsilon when the whole sequence is nullable."""
    if not sequence or tuple(sequence) == (epsilon,):
        return {epsilon}

    result: SymbolSet = set()
    all_nullable = True

    for symbol in sequence:
        # Epsilon contributes no terminal and allows us to inspect the next symbol.
        if symbol == epsilon:
            continue

        if symbol not in non_terminals:
            # A terminal begins the remaining sequence.
            result.add(symbol)
            all_nullable = False
            break

        symbol_first = first_sets[symbol]
        result.update(symbol_first - {epsilon})

        if epsilon not in symbol_first:
            all_nullable = False
            break

    if all_nullable:
        result.add(epsilon)

    return result


def compute_first_sets(
    productions: Sequence[Production] = PRODUCTIONS,
    epsilon: str = NULL,
) -> Dict[str, SymbolSet]:
    """Calculate FIRST for every non-terminal using a fixed-point algorithm."""
    non_terminals = _get_non_terminals(productions)
    first: Dict[str, SymbolSet] = {symbol: set() for symbol in non_terminals}

    changed = True
    while changed:
        changed = False
        for production in productions:
            production_first = first_of_sequence(
                production.rhs, first, non_terminals, epsilon
            )
            before = len(first[production.lhs])
            first[production.lhs].update(production_first)
            if len(first[production.lhs]) != before:
                changed = True

    return first


def compute_follow_sets(
    productions: Sequence[Production] = PRODUCTIONS,
    start_symbol: str = START_SYMBOL,
    first_sets: Mapping[str, SymbolSet] | None = None,
    epsilon: str = NULL,
    end_marker: str = END_MARKER,
) -> Dict[str, SymbolSet]:
    """Calculate FOLLOW for every non-terminal using a fixed-point algorithm."""
    non_terminals = _get_non_terminals(productions)
    if first_sets is None:
        first_sets = compute_first_sets(productions, epsilon)

    follow: Dict[str, SymbolSet] = {symbol: set() for symbol in non_terminals}
    follow[start_symbol].add(end_marker)

    changed = True
    while changed:
        changed = False

        for production in productions:
            rhs = production.rhs
            for index, symbol in enumerate(rhs):
                if symbol not in non_terminals:
                    continue

                suffix = rhs[index + 1 :]
                suffix_first = first_of_sequence(
                    suffix, first_sets, non_terminals, epsilon
                )

                # FIRST of everything after this symbol, excluding epsilon.
                additions = suffix_first - {epsilon}

                # If the suffix can disappear (including an empty suffix),
                # everything following the production's LHS follows this symbol.
                if epsilon in suffix_first:
                    additions = additions | follow[production.lhs]

                before = len(follow[symbol])
                follow[symbol].update(additions)
                if len(follow[symbol]) != before:
                    changed = True

    return follow


def compute_predict_sets(
    productions: Sequence[Production] = PRODUCTIONS,
    first_sets: Mapping[str, SymbolSet] | None = None,
    follow_sets: Mapping[str, SymbolSet] | None = None,
    epsilon: str = NULL,
) -> Dict[int, SymbolSet]:
    """Calculate PREDICT for each rule, keyed by its unique rule_id."""
    non_terminals = _get_non_terminals(productions)
    if first_sets is None:
        first_sets = compute_first_sets(productions, epsilon)
    if follow_sets is None:
        follow_sets = compute_follow_sets(
            productions, first_sets=first_sets, epsilon=epsilon
        )

    predict: Dict[int, SymbolSet] = {}
    for production in productions:
        production_first = first_of_sequence(
            production.rhs, first_sets, non_terminals, epsilon
        )
        rule_predict = production_first - {epsilon}

        if epsilon in production_first:
            rule_predict.update(follow_sets[production.lhs])

        predict[production.rule_id] = rule_predict

    return predict


def derive_grammar_sets(
    productions: Sequence[Production] = PRODUCTIONS,
    start_symbol: str = START_SYMBOL,
    epsilon: str = NULL,
    end_marker: str = END_MARKER,
) -> GrammarSets:
    """Validate the CFG and derive FIRST, FOLLOW, PREDICT, terminals, and non-terminals."""
    _validate_grammar(productions, start_symbol, epsilon)
    non_terminals = _get_non_terminals(productions)

    first = compute_first_sets(productions, epsilon)
    follow = compute_follow_sets(
        productions,
        start_symbol=start_symbol,
        first_sets=first,
        epsilon=epsilon,
        end_marker=end_marker,
    )
    predict = compute_predict_sets(
        productions, first_sets=first, follow_sets=follow, epsilon=epsilon
    )

    terminals = {
        symbol
        for production in productions
        for symbol in production.rhs
        if symbol not in non_terminals and symbol != epsilon
    }

    return GrammarSets(
        first=first,
        follow=follow,
        predict=predict,
        non_terminals=non_terminals,
        terminals=terminals,
    )


def find_predict_conflicts(
    productions: Sequence[Production], predict_sets: Mapping[int, SymbolSet]
) -> List[Tuple[Production, Production, SymbolSet]]:
    """Return pairs of same-LHS productions whose PREDICT sets overlap."""
    by_lhs: Dict[str, List[Production]] = defaultdict(list)
    for production in productions:
        by_lhs[production.lhs].append(production)

    conflicts: List[Tuple[Production, Production, SymbolSet]] = []
    for same_lhs_productions in by_lhs.values():
        same_lhs_productions.sort(key=lambda item: item.rule_id)
        for index, first_production in enumerate(same_lhs_productions):
            for second_production in same_lhs_productions[index + 1 :]:
                overlap = (
                    predict_sets[first_production.rule_id]
                    & predict_sets[second_production.rule_id]
                )
                if overlap:
                    conflicts.append((first_production, second_production, overlap))

    conflicts.sort(key=lambda item: (item[0].rule_id, item[1].rule_id))
    return conflicts


def _format_set(symbols: Iterable[str]) -> str:
    return "{ " + ", ".join(repr(symbol) for symbol in sorted(symbols)) + " }"


def _non_terminals_in_production_order(
    productions: Sequence[Production],
) -> List[Tuple[int, str]]:
    """Return each LHS once, ordered by the ID of its first production."""
    first_rule_by_lhs: Dict[str, int] = {}
    for production in sorted(productions, key=lambda item: item.rule_id):
        first_rule_by_lhs.setdefault(production.lhs, production.rule_id)

    return sorted(
        ((rule_id, lhs) for lhs, rule_id in first_rule_by_lhs.items()),
        key=lambda item: item[0],
    )


def print_grammar_sets(
    grammar_sets: GrammarSets,
    productions: Sequence[Production] = PRODUCTIONS,
    show_predict: bool = True,
) -> None:
    """Print sets in CFG production-ID order, rather than alphabetically by LHS."""
    ordered_productions = sorted(productions, key=lambda item: item.rule_id)
    ordered_non_terminals = _non_terminals_in_production_order(ordered_productions)

    print("FIRST SETS (ordered by first production ID)")
    for first_rule_id, non_terminal in ordered_non_terminals:
        print(
            f"FIRST(R{first_rule_id}, {non_terminal}) = "
            f"{_format_set(grammar_sets.first[non_terminal])}"
        )

    print("\nFOLLOW SETS (ordered by first production ID)")
    for first_rule_id, non_terminal in ordered_non_terminals:
        print(
            f"FOLLOW(R{first_rule_id}, {non_terminal}) = "
            f"{_format_set(grammar_sets.follow[non_terminal])}"
        )

    if show_predict:
        print("\nPREDICT SETS (ordered by production ID)")
        for production in ordered_productions:
            rhs = " ".join(production.rhs)
            print(
                f"PREDICT(R{production.rule_id}: {production.lhs} -> {rhs}) = "
                f"{_format_set(grammar_sets.predict[production.rule_id])}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Derive FIRST, FOLLOW, and PREDICT sets from CFG.py."
    )
    parser.add_argument(
        "--no-predict",
        action="store_true",
        help="Omit the PREDICT sets from the output.",
    )
    parser.add_argument(
        "--check-ll1",
        action="store_true",
        help="Also report overlapping PREDICT sets for alternatives of the same non-terminal.",
    )
    args = parser.parse_args()

    grammar_sets = derive_grammar_sets()
    print_grammar_sets(
        grammar_sets,
        show_predict=not args.no_predict,
    )

    if args.check_ll1:
        conflicts = find_predict_conflicts(PRODUCTIONS, grammar_sets.predict)
        print("\nPREDICT CONFLICTS (potential LL(1) conflicts)")
        if not conflicts:
            print("No PREDICT conflicts found.")
        else:
            for first_prod, second_prod, overlap in conflicts:
                print(
                    f"R{first_prod.rule_id} and R{second_prod.rule_id} "
                    f"for {first_prod.lhs}: {_format_set(overlap)}"
                )


# Derive the sets on import so a parser can simply import FIRST, FOLLOW, and PREDICT.
GRAMMAR_SETS = derive_grammar_sets()
FIRST_SET = GRAMMAR_SETS.first
FOLLOW_SET = GRAMMAR_SETS.follow
PREDICT_SET = GRAMMAR_SETS.predict
NON_TERMINALS = GRAMMAR_SETS.non_terminals
TERMINALS = GRAMMAR_SETS.terminals


if __name__ == "__main__":
    main()
