"""Tests for master device control in compressor groups."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from .conftest import (
    SAMPLE_ROOM,
    _create_coordinator,
    _make_store_mock,
    make_mock_states_get,
)


def _make_master_state(hvac_mode="off", hvac_modes=None):
    """Create a mock state for a master entity."""
    if hvac_modes is None:
        hvac_modes = ["off", "heat", "cool", "auto"]
    state = MagicMock()
    state.state = hvac_mode
    state.attributes = {"hvac_modes": hvac_modes}
    return state


def _room_with_device(area_id, entity_id, **overrides):
    """Create a room dict with one device."""
    room = {
        **SAMPLE_ROOM,
        "area_id": area_id,
        "thermostats": [entity_id],
        "acs": [],
        "devices": [
            {
                "entity_id": entity_id,
                "type": "trv",
                "role": "auto",
                "heating_system_type": "",
            }
        ],
    }
    room.update(overrides)
    return room


class TestMasterDeviceControl:
    """Tests for master device control wiring in the coordinator."""

    @pytest.mark.asyncio
    async def test_master_turns_on_heat_when_room_heating(self, hass, mock_config_entry):
        """Master entity should be set to 'heat' when a room is heating."""
        room = _room_with_device("living_room_abc12345", "climate.living_trv")
        store = _make_store_mock({"living_room_abc12345": room})
        store.get_settings.return_value = {
            "climate_control_active": True,
            "compressor_groups": [
                {
                    "id": "g1",
                    "name": "G1",
                    "members": ["climate.living_trv"],
                    "master_entity": "climate.boiler",
                }
            ],
        }

        master_state = _make_master_state("off")

        # temp=18.0 with comfort_temp=21.0 -> room will be heating
        base_get = make_mock_states_get(temp="18.0")

        def states_get(eid):
            if eid == "climate.boiler":
                return master_state
            return base_get(eid)

        hass.states.get = MagicMock(side_effect=states_get)
        hass.services.async_call = AsyncMock()
        hass.data = {"roommind": {"store": store}}

        coordinator = _create_coordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        # Check that set_hvac_mode was called on the master with "heat"
        calls = [
            c
            for c in hass.services.async_call.call_args_list
            if len(c.args) >= 3
            and c.args[0] == "climate"
            and c.args[1] == "set_hvac_mode"
            and c.args[2].get("entity_id") == "climate.boiler"
        ]
        assert len(calls) >= 1
        assert calls[-1].args[2]["hvac_mode"] == "heat"

    @pytest.mark.asyncio
    async def test_master_turns_off_when_all_idle(self, hass, mock_config_entry):
        """Master entity should be set to 'off' when all rooms are idle."""
        room = _room_with_device(
            "living_room_abc12345",
            "climate.living_trv",
            comfort_temp=20.0,
            eco_temp=17.0,
        )
        store = _make_store_mock({"living_room_abc12345": room})
        store.get_settings.return_value = {
            "climate_control_active": True,
            "compressor_groups": [
                {
                    "id": "g1",
                    "name": "G1",
                    "members": ["climate.living_trv"],
                    "master_entity": "climate.boiler",
                }
            ],
        }

        # Master currently on
        master_state = _make_master_state("heat")

        # temp=22.0 above comfort target -> room should be idle
        base_get = make_mock_states_get(temp="22.0")

        def states_get(eid):
            if eid == "climate.boiler":
                return master_state
            return base_get(eid)

        hass.states.get = MagicMock(side_effect=states_get)
        hass.services.async_call = AsyncMock()
        hass.data = {"roommind": {"store": store}}

        coordinator = _create_coordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        calls = [
            c
            for c in hass.services.async_call.call_args_list
            if len(c.args) >= 3
            and c.args[0] == "climate"
            and c.args[1] == "set_hvac_mode"
            and c.args[2].get("entity_id") == "climate.boiler"
        ]
        assert len(calls) >= 1
        assert calls[-1].args[2]["hvac_mode"] == "off"

    @pytest.mark.asyncio
    async def test_group_without_master_no_commands(self, hass, mock_config_entry):
        """Group without master_entity should not generate any master commands."""
        room = _room_with_device("living_room_abc12345", "climate.living_trv")
        store = _make_store_mock({"living_room_abc12345": room})
        store.get_settings.return_value = {
            "climate_control_active": True,
            "compressor_groups": [
                {
                    "id": "g1",
                    "name": "G1",
                    "members": ["climate.living_trv"],
                    # no master_entity
                }
            ],
        }

        hass.states.get = MagicMock(side_effect=make_mock_states_get(temp="18.0"))
        hass.services.async_call = AsyncMock()
        hass.data = {"roommind": {"store": store}}

        coordinator = _create_coordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        # No calls to any entity other than the room's TRV
        master_calls = [
            c
            for c in hass.services.async_call.call_args_list
            if len(c.args) >= 3
            and c.args[0] == "climate"
            and c.args[1] == "set_hvac_mode"
            and c.args[2].get("entity_id") not in ("climate.living_trv",)
        ]
        assert len(master_calls) == 0

    @pytest.mark.asyncio
    async def test_master_no_redundant_calls(self, hass, mock_config_entry):
        """Master should not be called when already in the correct mode."""
        room = _room_with_device("living_room_abc12345", "climate.living_trv")
        store = _make_store_mock({"living_room_abc12345": room})
        store.get_settings.return_value = {
            "climate_control_active": True,
            "compressor_groups": [
                {
                    "id": "g1",
                    "name": "G1",
                    "members": ["climate.living_trv"],
                    "master_entity": "climate.boiler",
                }
            ],
        }

        # Master already in "heat" mode, room is heating (temp below target)
        master_state = _make_master_state("heat")
        base_get = make_mock_states_get(temp="18.0")

        def states_get(eid):
            if eid == "climate.boiler":
                return master_state
            return base_get(eid)

        hass.states.get = MagicMock(side_effect=states_get)
        hass.services.async_call = AsyncMock()
        hass.data = {"roommind": {"store": store}}

        coordinator = _create_coordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        # No set_hvac_mode call to boiler (already correct)
        boiler_calls = [
            c
            for c in hass.services.async_call.call_args_list
            if len(c.args) >= 3
            and c.args[0] == "climate"
            and c.args[1] == "set_hvac_mode"
            and c.args[2].get("entity_id") == "climate.boiler"
        ]
        assert len(boiler_calls) == 0

    @pytest.mark.asyncio
    async def test_master_unavailable_skipped(self, hass, mock_config_entry):
        """Unavailable master entity should be skipped without crashing."""
        room = _room_with_device("living_room_abc12345", "climate.living_trv")
        store = _make_store_mock({"living_room_abc12345": room})
        store.get_settings.return_value = {
            "climate_control_active": True,
            "compressor_groups": [
                {
                    "id": "g1",
                    "name": "G1",
                    "members": ["climate.living_trv"],
                    "master_entity": "climate.boiler",
                }
            ],
        }

        unavailable = MagicMock()
        unavailable.state = "unavailable"
        unavailable.attributes = {}

        base_get = make_mock_states_get(temp="18.0")

        def states_get(eid):
            if eid == "climate.boiler":
                return unavailable
            return base_get(eid)

        hass.states.get = MagicMock(side_effect=states_get)
        hass.services.async_call = AsyncMock()
        hass.data = {"roommind": {"store": store}}

        coordinator = _create_coordinator(hass, mock_config_entry)
        # Should not raise
        await coordinator._async_update_data()

        # No master commands
        boiler_calls = [
            c
            for c in hass.services.async_call.call_args_list
            if len(c.args) >= 3 and c.args[2].get("entity_id") == "climate.boiler"
        ]
        assert len(boiler_calls) == 0

    @pytest.mark.asyncio
    async def test_master_mode_fallback_to_auto(self, hass, mock_config_entry):
        """Master that only supports 'auto' should get 'auto' when heating is needed."""
        room = _room_with_device("living_room_abc12345", "climate.living_trv")
        store = _make_store_mock({"living_room_abc12345": room})
        store.get_settings.return_value = {
            "climate_control_active": True,
            "compressor_groups": [
                {
                    "id": "g1",
                    "name": "G1",
                    "members": ["climate.living_trv"],
                    "master_entity": "climate.boiler",
                }
            ],
        }

        # Master only supports auto and off
        master_state = _make_master_state("off", hvac_modes=["auto", "off"])
        base_get = make_mock_states_get(temp="18.0")

        def states_get(eid):
            if eid == "climate.boiler":
                return master_state
            return base_get(eid)

        hass.states.get = MagicMock(side_effect=states_get)
        hass.services.async_call = AsyncMock()
        hass.data = {"roommind": {"store": store}}

        coordinator = _create_coordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        boiler_calls = [
            c
            for c in hass.services.async_call.call_args_list
            if len(c.args) >= 3
            and c.args[0] == "climate"
            and c.args[1] == "set_hvac_mode"
            and c.args[2].get("entity_id") == "climate.boiler"
        ]
        assert len(boiler_calls) >= 1
        assert boiler_calls[-1].args[2]["hvac_mode"] == "auto"

    @pytest.mark.asyncio
    async def test_master_action_script_called(self, hass, mock_config_entry):
        """Action script should be called with correct variables on transition."""
        room = _room_with_device("living_room_abc12345", "climate.living_trv")
        store = _make_store_mock({"living_room_abc12345": room})
        store.get_settings.return_value = {
            "climate_control_active": True,
            "compressor_groups": [
                {
                    "id": "g1",
                    "name": "G1",
                    "members": ["climate.living_trv"],
                    "master_entity": "climate.boiler",
                    "action_script": "script.boiler_hook",
                }
            ],
        }

        master_state = _make_master_state("off")
        script_state = MagicMock()
        script_state.state = "off"

        base_get = make_mock_states_get(temp="18.0")

        def states_get(eid):
            if eid == "climate.boiler":
                return master_state
            if eid == "script.boiler_hook":
                return script_state
            return base_get(eid)

        hass.states.get = MagicMock(side_effect=states_get)
        hass.services.async_call = AsyncMock()
        hass.data = {"roommind": {"store": store}}

        coordinator = _create_coordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        script_calls = [
            c
            for c in hass.services.async_call.call_args_list
            if len(c.args) >= 3 and c.args[0] == "script" and c.args[1] == "turn_on"
        ]
        assert len(script_calls) >= 1
        call_data = script_calls[-1].args[2]
        assert call_data["entity_id"] == "script.boiler_hook"
        assert call_data["variables"]["action"] == "heat"
        assert call_data["variables"]["master_entity"] == "climate.boiler"
        assert call_data["variables"]["members"] == ["climate.living_trv"]

    @pytest.mark.asyncio
    async def test_master_idle_when_climate_globally_disabled(self, hass, mock_config_entry):
        """Master should go idle when climate_control_active is False."""
        room = _room_with_device("living_room_abc12345", "climate.living_trv")
        store = _make_store_mock({"living_room_abc12345": room})
        store.get_settings.return_value = {
            "climate_control_active": False,
            "compressor_groups": [
                {
                    "id": "g1",
                    "name": "G1",
                    "members": ["climate.living_trv"],
                    "master_entity": "climate.boiler",
                }
            ],
        }

        # Master currently heating
        master_state = _make_master_state("heat")
        base_get = make_mock_states_get(temp="18.0")

        def states_get(eid):
            if eid == "climate.boiler":
                return master_state
            return base_get(eid)

        hass.states.get = MagicMock(side_effect=states_get)
        hass.services.async_call = AsyncMock()
        hass.data = {"roommind": {"store": store}}

        coordinator = _create_coordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        boiler_calls = [
            c
            for c in hass.services.async_call.call_args_list
            if len(c.args) >= 3
            and c.args[0] == "climate"
            and c.args[1] == "set_hvac_mode"
            and c.args[2].get("entity_id") == "climate.boiler"
        ]
        assert len(boiler_calls) >= 1
        assert boiler_calls[-1].args[2]["hvac_mode"] == "off"

    @pytest.mark.asyncio
    async def test_master_missing_entity_returns_none(self, hass, mock_config_entry):
        """Master entity that does not exist in HA should be skipped."""
        room = _room_with_device("living_room_abc12345", "climate.living_trv")
        store = _make_store_mock({"living_room_abc12345": room})
        store.get_settings.return_value = {
            "climate_control_active": True,
            "compressor_groups": [
                {
                    "id": "g1",
                    "name": "G1",
                    "members": ["climate.living_trv"],
                    "master_entity": "climate.nonexistent_boiler",
                }
            ],
        }

        # states.get returns None for the master entity (not registered)
        base_get = make_mock_states_get(temp="18.0")

        def states_get(eid):
            if eid == "climate.nonexistent_boiler":
                return None
            return base_get(eid)

        hass.states.get = MagicMock(side_effect=states_get)
        hass.services.async_call = AsyncMock()
        hass.data = {"roommind": {"store": store}}

        coordinator = _create_coordinator(hass, mock_config_entry)
        # Should not raise
        await coordinator._async_update_data()

        # No master commands sent
        boiler_calls = [
            c
            for c in hass.services.async_call.call_args_list
            if len(c.args) >= 3 and c.args[2].get("entity_id") == "climate.nonexistent_boiler"
        ]
        assert len(boiler_calls) == 0

    @pytest.mark.asyncio
    async def test_master_multi_room_mixed_modes(self, hass, mock_config_entry):
        """Master with multiple rooms. Heating priority resolves to 'heat'."""
        room_a = _room_with_device("room_a", "climate.trv_a")
        room_b = {
            **_room_with_device("room_b", "climate.ac_b"),
            "thermostats": [],
            "acs": ["climate.ac_b"],
            "devices": [
                {
                    "entity_id": "climate.ac_b",
                    "type": "ac",
                    "role": "auto",
                    "heating_system_type": "",
                }
            ],
            "climate_mode": "cool_only",
            "temperature_sensor": "sensor.room_b_temp",
            "humidity_sensor": "sensor.room_b_humidity",
            "schedules": [{"entity_id": "schedule.room_b_heating"}],
        }
        store = _make_store_mock({"room_a": room_a, "room_b": room_b})
        store.get_settings.return_value = {
            "climate_control_active": True,
            "compressor_groups": [
                {
                    "id": "g1",
                    "name": "G1",
                    "members": ["climate.trv_a", "climate.ac_b"],
                    "master_entity": "climate.boiler",
                    # default conflict_resolution = heating_priority
                }
            ],
        }

        master_state = _make_master_state("off")

        # room_a: temp=18 (below 21 comfort) -> heating
        # room_b: temp=28 (above 24 comfort_cool for cool_only) -> cooling
        base_get = make_mock_states_get(temp="18.0")

        ac_b_state = MagicMock()
        ac_b_state.state = "off"
        ac_b_state.attributes = {
            "hvac_modes": ["cool", "off"],
            "min_temp": 16,
            "max_temp": 30,
        }

        room_b_temp = MagicMock()
        room_b_temp.state = "28.0"
        room_b_temp.attributes = {}

        room_b_humidity = MagicMock()
        room_b_humidity.state = "55.0"
        room_b_humidity.attributes = {}

        room_b_schedule = MagicMock()
        room_b_schedule.state = "on"
        room_b_schedule.attributes = {}

        def states_get(eid):
            if eid == "climate.boiler":
                return master_state
            if eid == "climate.ac_b":
                return ac_b_state
            if eid == "sensor.room_b_temp":
                return room_b_temp
            if eid == "sensor.room_b_humidity":
                return room_b_humidity
            if eid == "schedule.room_b_heating":
                return room_b_schedule
            return base_get(eid)

        hass.states.get = MagicMock(side_effect=states_get)
        hass.services.async_call = AsyncMock()
        hass.data = {"roommind": {"store": store}}

        coordinator = _create_coordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        boiler_calls = [
            c
            for c in hass.services.async_call.call_args_list
            if len(c.args) >= 3
            and c.args[0] == "climate"
            and c.args[1] == "set_hvac_mode"
            and c.args[2].get("entity_id") == "climate.boiler"
        ]
        # With heating_priority (default), should resolve to "heat"
        assert len(boiler_calls) >= 1
        assert boiler_calls[-1].args[2]["hvac_mode"] == "heat"

    @pytest.mark.asyncio
    async def test_master_min_run_prevents_early_shutoff(self, hass, mock_config_entry):
        """Master must stay active for min_run_minutes before switching to idle."""
        room = _room_with_device(
            "living_room_abc12345",
            "climate.living_trv",
            comfort_temp=20.0,
        )
        store = _make_store_mock({"living_room_abc12345": room})
        store.get_settings.return_value = {
            "climate_control_active": True,
            "compressor_groups": [
                {
                    "id": "g1",
                    "name": "G1",
                    "members": ["climate.living_trv"],
                    "master_entity": "climate.boiler",
                    "min_run_minutes": 15,
                    "min_off_minutes": 5,
                }
            ],
        }

        # Master is currently heating
        master_state = _make_master_state("heat")
        # Room is at target → would want idle, but min-run should block
        base_get = make_mock_states_get(temp="22.0")

        def states_get(eid):
            if eid == "climate.boiler":
                return master_state
            return base_get(eid)

        hass.states.get = MagicMock(side_effect=states_get)
        hass.services.async_call = AsyncMock()
        hass.data = {"roommind": {"store": store}}

        coordinator = _create_coordinator(hass, mock_config_entry)

        # Load groups first so state tracking works, then simulate recent heat start
        coordinator._compressor_manager.load_groups(store.get_settings.return_value["compressor_groups"])
        coordinator._compressor_manager.set_master_action("g1", "heat")

        await coordinator._async_update_data()

        # Master should NOT have received an "off" command (min-run blocks it)
        boiler_off_calls = [
            c
            for c in hass.services.async_call.call_args_list
            if len(c.args) >= 3
            and c.args[0] == "climate"
            and c.args[1] == "set_hvac_mode"
            and c.args[2].get("entity_id") == "climate.boiler"
            and c.args[2].get("hvac_mode") == "off"
        ]
        assert len(boiler_off_calls) == 0

    @pytest.mark.asyncio
    async def test_master_min_off_prevents_early_restart(self, hass, mock_config_entry):
        """Master must stay off for min_off_minutes before restarting."""
        room = _room_with_device("living_room_abc12345", "climate.living_trv")
        store = _make_store_mock({"living_room_abc12345": room})
        store.get_settings.return_value = {
            "climate_control_active": True,
            "compressor_groups": [
                {
                    "id": "g1",
                    "name": "G1",
                    "members": ["climate.living_trv"],
                    "master_entity": "climate.boiler",
                    "min_run_minutes": 15,
                    "min_off_minutes": 5,
                }
            ],
        }

        # Master is currently off, room wants heating
        master_state = _make_master_state("off")
        base_get = make_mock_states_get(temp="18.0")

        def states_get(eid):
            if eid == "climate.boiler":
                return master_state
            return base_get(eid)

        hass.states.get = MagicMock(side_effect=states_get)
        hass.services.async_call = AsyncMock()
        hass.data = {"roommind": {"store": store}}

        coordinator = _create_coordinator(hass, mock_config_entry)

        # Load groups first, then simulate recent off transition
        coordinator._compressor_manager.load_groups(store.get_settings.return_value["compressor_groups"])
        coordinator._compressor_manager.set_master_action("g1", "heat")
        coordinator._compressor_manager.set_master_action("g1", "idle")

        await coordinator._async_update_data()

        # Master should NOT have received a "heat" command (min-off blocks it)
        boiler_heat_calls = [
            c
            for c in hass.services.async_call.call_args_list
            if len(c.args) >= 3
            and c.args[0] == "climate"
            and c.args[1] == "set_hvac_mode"
            and c.args[2].get("entity_id") == "climate.boiler"
            and c.args[2].get("hvac_mode") == "heat"
        ]
        assert len(boiler_heat_calls) == 0

    @pytest.mark.asyncio
    async def test_master_no_state_update_when_mode_unsupported(self, hass, mock_config_entry):
        """When resolved_mode is None, state should NOT be updated (K3 fix)."""
        room = _room_with_device("living_room_abc12345", "climate.living_trv")
        store = _make_store_mock({"living_room_abc12345": room})
        store.get_settings.return_value = {
            "climate_control_active": True,
            "compressor_groups": [
                {
                    "id": "g1",
                    "name": "G1",
                    "members": ["climate.living_trv"],
                    "master_entity": "climate.boiler",
                }
            ],
        }

        # Master only supports "heat" and "off" — no "cool", "auto", or "heat_cool"
        master_state = _make_master_state("off", hvac_modes=["off", "heat"])

        # Set up room to want cooling (but master can't cool)
        room_ac = {
            **_room_with_device("living_room_abc12345", "climate.living_trv"),
            "thermostats": [],
            "acs": ["climate.living_trv"],
            "devices": [
                {
                    "entity_id": "climate.living_trv",
                    "type": "ac",
                    "role": "auto",
                    "heating_system_type": "",
                }
            ],
            "climate_mode": "cool_only",
        }
        store = _make_store_mock({"living_room_abc12345": room_ac})
        store.get_settings.return_value = {
            "climate_control_active": True,
            "compressor_groups": [
                {
                    "id": "g1",
                    "name": "G1",
                    "members": ["climate.living_trv"],
                    "master_entity": "climate.boiler",
                }
            ],
        }

        ac_state = MagicMock()
        ac_state.state = "off"
        ac_state.attributes = {"hvac_modes": ["cool", "off"], "min_temp": 16, "max_temp": 30}

        base_get = make_mock_states_get(temp="30.0")

        def states_get(eid):
            if eid == "climate.boiler":
                return master_state
            if eid == "climate.living_trv":
                return ac_state
            return base_get(eid)

        hass.states.get = MagicMock(side_effect=states_get)
        hass.services.async_call = AsyncMock()
        hass.data = {"roommind": {"store": store}}

        coordinator = _create_coordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        # No command should have been sent to the master
        boiler_calls = [
            c
            for c in hass.services.async_call.call_args_list
            if len(c.args) >= 3
            and c.args[0] == "climate"
            and c.args[1] == "set_hvac_mode"
            and c.args[2].get("entity_id") == "climate.boiler"
        ]
        assert len(boiler_calls) == 0

        # State should NOT have been updated to "cool"
        state = coordinator._compressor_manager.get_state("g1")
        assert state.master_action != "cool"
