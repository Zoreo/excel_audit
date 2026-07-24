from excel_auditor.parsing.formula_normalizer import normalize_formula


def test_copied_formulas_normalize_identically():
    # D2 = B2*C2, D3 = B3*C3, D4 = B4*C4 -> same relative pattern
    n2 = normalize_formula("=B2*C2", row=2, column=4)
    n3 = normalize_formula("=B3*C3", row=3, column=4)
    n4 = normalize_formula("=B4*C4", row=4, column=4)
    assert n2 == n3 == n4
    assert n2 == "RC[-2]*RC[-1]"


def test_different_formula_differs():
    n_ok = normalize_formula("=B9*C9", row=9, column=4)
    n_wrong = normalize_formula("=B8*C9", row=9, column=4)
    assert n_ok != n_wrong


def test_absolute_reference_is_anchor_independent():
    a = normalize_formula("=Assumptions!$B$2", row=2, column=3)
    b = normalize_formula("=Assumptions!$B$2", row=13, column=3)
    assert a == b == "ASSUMPTIONS!R2C2"


def test_absolute_vs_relative_differ():
    rel = normalize_formula("=B2", row=2, column=4)
    abs_ = normalize_formula("=$B$2", row=2, column=4)
    assert rel != abs_


def test_range_normalization():
    n = normalize_formula("=SUM(D2:D13)", row=14, column=4)
    assert n == "SUM(R[-12]C:R[-1]C)"


def test_sheet_reference_preserved_case_insensitively():
    a = normalize_formula("='Revenue Forecast'!D14", row=3, column=2)
    b = normalize_formula("='REVENUE FORECAST'!D14", row=3, column=2)
    assert a == b
    assert a is not None and a.startswith("REVENUE FORECAST!")


def test_function_names_uppercased():
    a = normalize_formula("=sum(A1:A2)", row=3, column=1)
    b = normalize_formula("=SUM(A1:A2)", row=3, column=1)
    assert a == b


def test_string_literals_untouched():
    n = normalize_formula('=IF(A1="b2","B2",A1)', row=1, column=2)
    assert n is not None
    assert '"b2"' in n and '"B2"' in n


def test_external_reference_marked():
    n = normalize_formula("='[Benchmarks.xlsx]Data'!B2", row=7, column=2)
    assert n is not None and n.startswith("[EXT:BENCHMARKS.XLSX]")


def test_non_formula_returns_none():
    assert normalize_formula("hello", row=1, column=1) is None
