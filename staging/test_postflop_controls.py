from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).with_name("source_1_3_101") / "PigeonPoker.pyw"
source_text = SOURCE.read_text(encoding="utf-8")
tree = ast.parse(source_text, filename=str(SOURCE))


def find_method(name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Missing method: {name}")


def contains_call(node: ast.AST, attr_name: str) -> bool:
    return any(
        isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == attr_name
        for item in ast.walk(node)
    )


def test_postflop_legal_controls_are_not_inside_preflop_only_branch() -> None:
    method = find_method("_refresh_table_windows")
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(method):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    generic_tries = []
    for node in ast.walk(method):
        if not isinstance(node, ast.Try):
            continue
        has_legal_lookup = any(
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr == "legal_actions"
            and isinstance(item.func.value, ast.Name)
            and item.func.value.id == "hand"
            for item in ast.walk(node)
        )
        has_action_buttons = contains_call(node, "_compact_action_button")
        has_bet_slider = any(
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr == "Scale"
            for item in ast.walk(node)
        )
        if has_legal_lookup and has_action_buttons and has_bet_slider:
            generic_tries.append(node)

    assert generic_tries, (
        "The normal CHECK/CALL/FOLD and BET/RAISE controls were not found."
    )

    for node in generic_tries:
        ancestor = parents.get(node)
        while ancestor is not None and ancestor is not method:
            if isinstance(ancestor, ast.If):
                test_text = ast.get_source_segment(source_text, ancestor.test) or ""
                if "hand.street" in test_text and "preflop" in test_text:
                    raise AssertionError(
                        "Generic legal-action UI is nested inside a preflop-only branch."
                    )
            ancestor = parents.get(ancestor)


def test_only_preflop_raise_sizing_uses_the_chart() -> None:
    method = find_method("_cash_human_action")
    method_source = ast.get_source_segment(source_text, method) or ""
    assert 'hand.street == "preflop"' in method_source
    assert "_fixed_preflop_raise_target" in method_source
    assert "PREFLOP CHART LINE NOT COVERED" not in method_source
    assert "USE THE CHART ACTIONS AND BB SIZE ONLY" not in method_source


if __name__ == "__main__":
    test_postflop_legal_controls_are_not_inside_preflop_only_branch()
    print("PASS postflop controls are generated outside the preflop-only branch")
    test_only_preflop_raise_sizing_uses_the_chart()
    print("PASS preflop chart gate remains in place")
    print("ALL PASS 2 postflop UI regression tests")
