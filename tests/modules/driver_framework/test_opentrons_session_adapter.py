"""Session configuration is converted only at the vendor adapter."""
from unittest.mock import patch, sentinel

import pytest

pytest.importorskip("culsma_opentrons")

from culsma_os.driver_framework.adapters.opentrons import OpentronsSessionAdapter


def test_session_adapter_converts_configuration_and_forwards_state_directory():
    configuration = {'device_id': 'station'}
    with patch('culsma_opentrons.config.DeckConfiguration.from_dict', return_value=sentinel.deck) as convert, \
         patch('culsma_opentrons.plugin.SimulatorSessionFactory.create', return_value=sentinel.session) as create:
        actual = OpentronsSessionAdapter().create(configuration, sentinel.artifacts, state_dir=sentinel.state)
    assert actual is sentinel.session
    convert.assert_called_once_with(configuration)
    create.assert_called_once_with(sentinel.deck, sentinel.artifacts, state_dir=sentinel.state)


def test_session_adapter_defaults_to_no_persistent_state_directory():
    with patch('culsma_opentrons.config.DeckConfiguration.from_dict', return_value=sentinel.deck), \
         patch('culsma_opentrons.plugin.SimulatorSessionFactory.create') as create:
        OpentronsSessionAdapter().create({}, sentinel.artifacts)
    create.assert_called_once_with(sentinel.deck, sentinel.artifacts, state_dir=None)
