"""Testes de derivação de MAC."""

from app.inventory.mac import derive_mac


def test_derive_mac_broetec_core() -> None:
    assert derive_mac('broetec-core') == '52:54:00:6d:81:73'


def test_derive_mac_node_01_legacy() -> None:
    assert derive_mac('node-01') == '52:54:00:34:29:e0'
