from __future__ import annotations

from documentledger.links import _proposal_links_for_section
from documentledger.source_index import index_python_source

READIO_SOURCE = """
class Readio:
    def speak(self):
        return None

    def render(self):
        return None

    def install_model(self):
        return None

    def update_model(self):
        return None

    def remove_model(self):
        return None
"""


def _inventory(source: str = READIO_SOURCE, path: str = "readio/api/service.py") -> dict[str, dict[str, object]]:
    return {unit.source_id: unit.to_record() for unit in index_python_source(path, source)}


def _propose(text: str, inventory: dict[str, dict[str, object]] | None = None):
    return _proposal_links_for_section(text, inventory or _inventory())


def test_exact_function_reference_suppresses_module_dependency() -> None:
    inventory = _inventory("def do_work():\n    return None\n", "readio/api/service.py")
    proposals, stats = _propose("Use `readio/api/service.py::do_work()`.\n", inventory)

    assert [item["source_unit"] for item in proposals] == ["py:function:readio/api/service.py::do_work"]
    assert stats["dominated_ancestors"] == 2


def test_exact_member_reference_suppresses_class_body_dependency() -> None:
    proposals, stats = _propose("## Engine model management\nUse `Readio.update_model()`.\n")

    assert [item["source_unit"] for item in proposals] == ["py:method:readio/api/service.py::Readio.update_model"]
    assert proposals[0]["coverage"] == "api-autodoc"
    assert proposals[0]["tracked_hashes"] == ["signature_hash", "docstring_hash", "public_contract_hash"]
    assert stats["dominated_ancestors"] == 1


def test_two_exact_member_references_produce_only_member_links() -> None:
    proposals, _ = _propose("Use `Readio.install_model(), Readio.update_model()`.\n")

    assert {item["source_unit"] for item in proposals} == {
        "py:method:readio/api/service.py::Readio.install_model",
        "py:method:readio/api/service.py::Readio.update_model",
    }
    assert not any(item["source_unit"] == "py:class:readio/api/service.py::Readio" for item in proposals)


def test_independent_class_claim_keeps_class_dependency() -> None:
    proposals, _ = _propose("The Readio facade owns engine and model lifecycle operations.\n\nUse `Readio.update_model()`.\n")

    assert {item["source_unit"] for item in proposals} == {
        "py:class:readio/api/service.py::Readio",
        "py:method:readio/api/service.py::Readio.update_model",
    }
    class_link = next(item for item in proposals if item["source_unit"].startswith("py:class:"))
    assert class_link["tracked_hashes"] == ["body_hash", "public_contract_hash"]


def test_ambiguous_unqualified_symbol_is_reported_without_a_guess() -> None:
    source = """
class First:
    def refresh(self):
        return None

class Second:
    def refresh(self):
        return None
"""
    proposals, stats = _propose("Use `refresh()`.\n", _inventory(source))

    assert proposals == []
    assert stats["ambiguous_matches"] == 1


def test_exact_source_directive_resolves_and_selects_hash_dimension() -> None:
    source_id = "py:method:readio/api/service.py::Readio.update_model"
    text = f'<!-- documentledger:\ndepends-on="{source_id}"\nwatch="public_contract"\n-->\n'

    proposals, _ = _propose(text)

    assert len(proposals) == 1
    assert proposals[0]["source_unit"] == source_id
    assert proposals[0]["tracked_hashes"] == ["public_contract_hash"]
    assert proposals[0]["confidence"] == "exact"


def test_test_units_are_excluded_unless_explicitly_enabled() -> None:
    test_inventory = _inventory("def test_public_api():\n    return None\n", "tests/test_api.py")

    excluded, stats = _propose("Use `test_public_api()`.\n", test_inventory)
    included, _ = _proposal_links_for_section("Use `test_public_api()`.\n", test_inventory, include_tests=True)

    assert excluded == []
    assert stats["excluded_test_units"] > 0
    assert any("tests/test_api.py" in item["source_unit"] for item in included)
