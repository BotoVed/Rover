from __future__ import annotations

from typing import Any, Callable

from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers import area_registry as ar, entity_registry as er
from homeassistant.helpers.event import Event, async_track_state_change_event


class HaBridge:
    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._on_state_changed: Callable[[str, Any], None] | None = None
        self._on_registry_changed: Callable[[], None] | None = None
        self._tracked_entities: set[str] = set()
        self._unsub_state: list = []
        self._unsub_registry: list = []

    def set_callbacks(
        self,
        on_state_changed: Callable[[str, Any], None] | None = None,
        on_registry_changed: Callable[[], None] | None = None,
    ) -> None:
        self._on_state_changed = on_state_changed
        self._on_registry_changed = on_registry_changed

    async def call_service(self, domain: str, service: str, data: dict) -> None:
        await self._hass.services.async_call(domain, service, data, blocking=True, limit=5)

    async def get_state(self, entity_id: str) -> State | None:
        return self._hass.states.get(entity_id)

    def start_tracking(self, entity_ids: list[str]) -> None:
        for eid in entity_ids:
            if eid not in self._tracked_entities:
                self._tracked_entities.add(eid)
        self._unsub_state.clear()
        if self._tracked_entities:
            unsub = async_track_state_change_event(
                self._hass,
                list(self._tracked_entities),
                self._handle_state_event,
            )
            self._unsub_state.append(unsub)

    def stop_tracking(self) -> None:
        for unsub in self._unsub_state:
            if unsub:
                unsub()
        self._unsub_state.clear()
        for unsub in self._unsub_registry:
            if unsub:
                unsub()
        self._unsub_registry.clear()

    def stop_tracking_entity(self, entity_id: str) -> None:
        self._tracked_entities.discard(entity_id)
        self._unsub_state.clear()
        if self._tracked_entities:
            unsub = async_track_state_change_event(
                self._hass,
                list(self._tracked_entities),
                self._handle_state_event,
            )
            self._unsub_state.append(unsub)

    @callback
    def _handle_state_event(self, event: Event) -> None:
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        if entity_id and new_state and entity_id in self._tracked_entities and self._on_state_changed:
            self._on_state_changed(entity_id, new_state)

    async def start_registry_listeners(self) -> None:
        unsub = self._hass.bus.async_listen(
            "entity_registry_updated", self._handle_registry_event
        )
        self._unsub_registry.append(unsub)
        unsub = self._hass.bus.async_listen(
            "area_registry_updated", self._handle_registry_event
        )
        self._unsub_registry.append(unsub)

    def _handle_registry_event(self, event: Any) -> None:
        if self._on_registry_changed:
            self._on_registry_changed()

    @property
    def entity_registry(self):
        return er.async_get(self._hass)

    @property
    def area_registry(self):
        return ar.async_get(self._hass)
