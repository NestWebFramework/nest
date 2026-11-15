from pathlib import Path

import pytest

from nest.contract import Contract, load_contracts
from nest.manifest import ManifestError, load_manifest, parse_manifest


def parse(raw: dict):
    return parse_manifest(raw, "test", Path("."))


def base(**sections):
    return {
        "module": {"name": "x", "id": "test.module.x", "type": "module", "version": "0.1.0"},
        **sections,
    }


def test_a_good_manifest_reads():
    m = parse(base(main="x", deps={"htmx": ">=0.1"}))
    assert m.id == "test.module.x" and str(m.version) == "0.1.0"
    assert m.deps == {"htmx": ">=0.1"}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"id": "NoDots"}, "an id is lower-case and dotted"),
        ({"version": "one"}, "is not a version"),
        ({"name": "Bad Name"}, "a name is lower-case"),
    ],
)
def test_identity_is_checked(change, message):
    raw = base()
    raw["module"].update(change)
    with pytest.raises(ManifestError) as e:
        parse(raw)
    assert message in str(e.value)


def test_a_typo_in_a_known_section_is_an_error():
    with pytest.raises(ManifestError) as e:
        parse(base(requires={"hosts": ["db"]}))
    assert "requires.hosts" in str(e.value)


def test_a_secret_setting_cannot_have_a_default():
    with pytest.raises(ManifestError) as e:
        parse(base(settings={"token": {"secret": True, "default": "abc"}}))
    assert "secret and cannot have a default" in str(e.value)


def test_bad_version_range_is_an_error():
    with pytest.raises(ManifestError) as e:
        parse(base(deps={"htmx": "around 1"}))
    assert "not a version range" in str(e.value)


def test_unknown_sections_are_kept_for_ecosystems():
    m = parse(base(main="x", tick={"stage": "npc"}))
    assert m.raw["tick"] == {"stage": "npc"}


def test_missing_file_and_bad_yaml(tmp_path):
    with pytest.raises(ManifestError, match="no such file"):
        load_manifest(tmp_path)
    (tmp_path / "module.yml").write_text("module: [unclosed")
    with pytest.raises(ManifestError, match="not valid YAML"):
        load_manifest(tmp_path)


def test_core_contract_rules():
    contract = load_contracts()
    assert contract.validate(parse(base(main="x"))) == []
    problems = contract.validate(parse(base()))
    assert problems == ["a module must declare 'main'"]
    problems = contract.validate(parse(base(main="x", application={"port": 1})))
    assert any("a module owns no port" in p for p in problems)


def test_an_unknown_type_names_the_known_ones():
    raw = base(main="x")
    raw["module"]["type"] = "gizmo"
    problems = load_contracts().validate(parse(raw))
    assert "type 'gizmo' is not known" in problems[0] and "module" in problems[0]


def test_an_ecosystem_contract_adds_and_refines_types():
    contract = load_contracts()
    contract.merge(
        Contract.from_mapping(
            {"ecosystem": "saga", "types": {"subsystem": {"required": ["main", "tick"]}}}, "saga"
        )
    )
    raw = base(main="x")
    raw["module"]["type"] = "subsystem"
    assert contract.validate(parse(raw)) == ["a subsystem must declare 'tick'"]
    raw["tick"] = {"stage": "npc"}
    assert contract.validate(parse(raw)) == []
    assert contract.ecosystems == ["nest", "saga"]
