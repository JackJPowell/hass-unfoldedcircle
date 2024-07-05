"""The Unfolded Circle Remote integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from websocket_server import WebsocketServer


class UCRWebSocket:

    @callback
    def state_automation_listener(
        self, state_event: Event[EventStateChangedData]
    ) -> any:
        entity = state_event.data["entity_id"]
        from_s = state_event.data["old_state"]
        to_s = state_event.data["new_state"]
        message = f"Entity ID: {entity}, from: {from_s}, to: {to_s}"
        self.server.send_message_to_all(message)

    # Called when a client sends a message
    def message_received(self, client, server, message):
        if len(message) > 200:
            message = message[:200] + ".."
        print("Listening to state changes for:", message)
        async_track_state_change_event(
            self.hass,
            [message],
            self.state_automation_listener,
        )

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.server = WebsocketServer(port=9001)
        self.server.set_fn_new_client(new_client)
        self.server.set_fn_client_left(client_left)
        self.server.set_fn_message_received(self.message_received)
        unsub = async_track_state_change_event(
            hass, ["light.bed_light", "fan.ceiling_fan"], self.state_automation_listener
        )
        self.server.run_forever(threaded=True)
        self.hass = hass
        self.config_entry = config_entry


def new_client(client, server):
    print("New client connected and was given id %d" % client["id"])
    server.send_message_to_all("Hey all, a new client has joined us")


# Called for every client disconnecting
def client_left(client, server):
    print("Client(%d) disconnected" % client["id"])
