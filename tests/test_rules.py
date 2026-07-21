from claims_audit.rules import RuleType, load_rules


def test_rules_load_and_are_unique():
    rs = load_rules()
    assert 10 <= len(rs) <= 20
    ids = [r.id for r in rs]
    assert len(ids) == len(set(ids)), "rule ids must be unique"


def test_every_rule_type_present():
    rs = load_rules()
    present = {r.type for r in rs}
    assert present == set(RuleType), f"missing rule types: {set(RuleType) - present}"


def test_lookup_by_id_and_ids_set():
    rs = load_rules()
    assert rs.by_id("R001") is not None
    assert rs.by_id("NOPE") is None
    assert "R001" in rs.ids()


def test_rule_params_shape():
    rs = load_rules()
    for r in rs.of_type(RuleType.MUE_UNITS):
        assert "code" in r.params and "max_units_per_day" in r.params
    for r in rs.of_type(RuleType.NCCI_PAIR):
        assert "code_a" in r.params and "code_b" in r.params
