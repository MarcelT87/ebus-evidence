import json

import pytest

from ebus_evidence.system_identity import (
    SystemIdentityError,
    build_system_document,
    load_system_document,
    parse_scan_result,
    topology_signature,
    validate_system_document,
)


def test_parse_scan_result_keeps_only_identity_fields():
    text = (
        "08;Vaillant;EHP00;0327;7201;21;07;45;0010002779;0006;secret-extra;N8\n"
        "15;Vaillant;UIH00;0374;6901;21;17;24;0020093224;0907;other-extra;N0\n"
    )

    devices = parse_scan_result(text)

    assert devices == [
        {
            "address": "08",
            "manufacturer": "Vaillant",
            "id": "EHP00",
            "sw": "0327",
            "hw": "7201",
        },
        {
            "address": "15",
            "manufacturer": "Vaillant",
            "id": "UIH00",
            "sw": "0374",
            "hw": "6901",
        },
    ]
    assert "0010002779" not in json.dumps(devices)


def test_parse_scan_result_accepts_empty_identification_and_dash_versions():
    devices = parse_scan_result("0c;Kromschroeder;  ;0204;-\n")
    assert devices[0]["id"] == ""
    assert devices[0]["hw"] == "-"


def test_parse_scan_result_sorts_by_bus_address_and_deduplicates_identical_lines():
    devices = parse_scan_result(
        "15;Vaillant;UIH00;0374;6901\n"
        "08;Vaillant;EHP00;0327;7201\n"
        "08;Vaillant;EHP00;0327;7201\n"
    )
    assert [item["address"] for item in devices] == ["08", "15"]


def test_parse_scan_result_rejects_conflicting_same_address():
    with pytest.raises(SystemIdentityError, match="conflicting scan results"):
        parse_scan_result(
            "08;Vaillant;HMU00;0902;5103\n"
            "08;Vaillant;HMU00;0903;5103\n"
        )


def test_topology_signature_is_order_and_case_stable():
    left = [
        {"address": "08", "manufacturer": "Vaillant", "id": "HMU00", "sw": "0902", "hw": "5103"},
        {"address": "15", "manufacturer": "Vaillant", "id": "CTLV2", "sw": "0515", "hw": "1104"},
    ]
    right = [
        {"address": "15", "manufacturer": "VAILLANT", "id": "ctlv2", "sw": "0515", "hw": "1104"},
        {"address": "08", "manufacturer": "vaillant", "id": "hmu00", "sw": "0902", "hw": "5103"},
    ]

    assert topology_signature(left) == topology_signature(right)


def test_declared_product_does_not_change_topology_signature():
    devices = parse_scan_result("08;Vaillant;HMU00;0902;5103\n")

    a = build_system_document(
        devices,
        declared_manufacturer="Vaillant",
        declared_model="TEST-MODEL",
    )
    b = build_system_document(
        devices,
        declared_manufacturer="Vaillant",
        declared_model="different label",
    )

    assert a["topology_signature_sha256"] == b["topology_signature_sha256"]
    assert a["declared_product"]["model"] == "TEST-MODEL"
    assert a["source"]["extra_scan_columns_retained"] is False


def test_system_document_rejects_extra_top_level_fields():
    devices = parse_scan_result("08;Vaillant;HMU00;0902;5103\n")
    document = build_system_document(devices)
    document["hostname"] = "must-not-be-shared"

    with pytest.raises(SystemIdentityError, match="unsupported top-level fields"):
        validate_system_document(document)


def test_system_document_rejects_tampered_signature():
    devices = parse_scan_result("08;Vaillant;HMU00;0902;5103\n")
    document = build_system_document(devices)
    document["topology_signature_sha256"] = "0" * 64

    with pytest.raises(SystemIdentityError, match="does not match devices"):
        validate_system_document(document)


def test_system_document_rejects_extra_declared_product_fields():
    devices = parse_scan_result("08;Vaillant;HMU00;0902;5103\n")
    document = build_system_document(
        devices,
        declared_manufacturer="Vaillant",
        declared_model="TEST-MODEL",
    )
    document["declared_product"]["serial"] = "private"

    with pytest.raises(SystemIdentityError, match="unsupported fields"):
        validate_system_document(document)


def test_system_identity_rejects_excessively_nested_local_structure(tmp_path):
    path = tmp_path / "system.json"
    nested = '{"x":' * 80 + '0' + '}' * 80
    path.write_text(
        '{"format":"ebus-evidence-system-v1","deep":' + nested + '}',
        encoding="utf-8",
    )

    with pytest.raises(SystemIdentityError, match="maximum nesting depth"):
        load_system_document(path)
