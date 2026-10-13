"""Testes do menu interativo (Textual) com o piloto, sem terminal real."""

from __future__ import annotations

from pathlib import Path

from textual.widgets import Input, SelectionList, Static

from app.scaffold.overlays import OverlayManager
from app.tui.app import OverlayWizard


async def _type(pilot, field_id: str, text: str) -> None:  # noqa: ANN001
    widget = pilot.app.query_one(f'#{field_id}', Input)
    widget.value = text
    await pilot.pause()


async def test_wizard_creates_a_local_overlay(lab_repo: Path) -> None:
    app = OverlayWizard(OverlayManager(lab_repo))
    async with app.run_test(size=(120, 50)) as pilot:
        assert app.step == 'base'
        await pilot.press('ctrl+n')
        assert app.step == 'components'
        await pilot.press('ctrl+n')
        assert app.step == 'vm'
        assert app.query_one('#ip', Input).value == '10.20.30.70'
        assert app.query_one('#memory-mb', Input).value == '8192'

        await _type(pilot, 'overlay-id', 'meu-lab')
        await _type(pilot, 'vcpus', '2')
        await pilot.press('ctrl+n')
        assert app.step == 'network'
        await pilot.press('ctrl+n')
        assert app.step == 'review'
        summary = str(app.query_one('#summary', Static).render())
        assert 'meu-lab' in summary
        assert 'https://argo.10-20-30-70.sslip.io' in summary

        await pilot.press('ctrl+n')
        assert app.step == 'done'
        await pilot.press('ctrl+n')

    created = app.return_value
    assert created is not None
    assert created.spec.overlay_id == 'meu-lab'
    assert created.size.vcpus == 2  # noqa: PLR2004
    assert (lab_repo / 'provisioning/inventory/meu-lab/hosts.ini').is_file()
    assert (
        lab_repo / 'k8s/core/applications/overlays/meu-lab/kustomization.yaml'
    ).is_file()


async def test_wizard_blocks_invalid_input(lab_repo: Path) -> None:
    app = OverlayWizard(OverlayManager(lab_repo))
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press('ctrl+n', 'ctrl+n')
        await _type(pilot, 'overlay-id', 'broetec-core')
        await pilot.press('ctrl+n')
        assert app.step == 'vm'
        error = str(app.query_one('#error', Static).render())
        assert 'reserved prefix' in error

        await _type(pilot, 'overlay-id', 'ok-lab')
        await _type(pilot, 'ip', '10.20.30.40')
        await pilot.press('ctrl+n')
        assert app.step == 'vm'
        assert 'already used' in str(app.query_one('#error', Static).render())

        await pilot.press('ctrl+b')
        assert app.step == 'components'
    assert app.return_value is None
    assert not (lab_repo / 'provisioning/inventory/manifest.local.yml').exists()


async def test_wizard_can_drop_an_optional_component(lab_repo: Path) -> None:
    app = OverlayWizard(OverlayManager(lab_repo))
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press('ctrl+n')
        choices = app.query_one('#component-choice', SelectionList)
        choices.deselect('core/external-secrets-operator')
        await pilot.pause()
        await pilot.press('ctrl+n')
        await _type(pilot, 'overlay-id', 'sem-eso')
        await pilot.press('ctrl+n', 'ctrl+n', 'ctrl+n')
        assert app.step == 'done'
    assert app.created is not None
    assert app.created.spec.k8s.disable == ('core/external-secrets-operator',)
