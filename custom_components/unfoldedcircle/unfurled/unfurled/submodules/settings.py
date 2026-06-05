"""Settings sub-object - configuration for the remote device."""

from __future__ import annotations

from typing import TYPE_CHECKING

from packaging.version import Version

from ..helpers.models import (
    BluetoothSettings,
    ButtonSettings,
    ConfigurationChangeEvent,
    DisplaySettings,
    Feature,
    HapticSettings,
    LocalizationInfo,
    NetworkSettings,
    PowerSavingSettings,
    ProfileSettings,
    SoftwareUpdateSettings,
    SoundSettings,
    UpdateType,
    VoiceSettings,
)
from .base import RemoteModule

if TYPE_CHECKING:
    from ..remote import Remote


class Settings(RemoteModule):
    """Manages all remote configuration settings.

    Accessed via ``remote.settings``. Populated automatically during
    :meth:`~unfurled.remote.Remote.init`. Individual sections can be updated
    with the ``update_*`` methods.

    Example::

        await remote.settings.update_display(brightness=80)
        await remote.settings.update_network(wake_on_wlan=True)
    """

    def __init__(self, remote: Remote) -> None:
        super().__init__(remote)
        self.display = DisplaySettings()
        self.button = ButtonSettings()
        self.sound = SoundSettings()
        self.haptic = HapticSettings()
        self.power_saving = PowerSavingSettings()
        self.network = NetworkSettings()
        self.software_update = SoftwareUpdateSettings()
        self.localization = LocalizationInfo()
        self.bluetooth = BluetoothSettings()
        self.profile = ProfileSettings()
        self.voice = VoiceSettings()
        self.features: list[Feature] = []

    # ------------------------------------------------------------------
    # Update methods
    # ------------------------------------------------------------------

    @property
    def internal_ir_enabled(self) -> bool:
        """Return ``True`` if the remote's built-in IR emitter is enabled."""
        return any(f.id == "internal_ir" and f.enabled for f in self.features)

    # ------------------------------------------------------------------
    # Locale helper
    # ------------------------------------------------------------------

    def get_text_for_locale(
        self,
        text: dict | str | None,
        *,
        locale: str | None = None,
        default_text: str = "Undefined",
    ) -> str:
        """Return the best match for the current locale from a text dict."""
        if not text:
            return default_text
        if isinstance(text, str):
            return text

        locale = locale or self.localization.language_code

        for candidate in (locale, locale.split("_")[0] if "_" in locale else None, "en_US", "en"):
            if candidate and text.get(candidate):
                return text[candidate]

        for v in text.values():
            if v:
                return v

        return default_text

    def _on_configuration_change(self, event: ConfigurationChangeEvent) -> None:
        state = event.new_state

        if display := state.get("display"):
            self.display.auto_brightness = display.get(
                "auto_brightness", self.display.auto_brightness
            )
            self.display.brightness = display.get("brightness", self.display.brightness)

        if button := state.get("button"):
            self.button.auto_brightness = button.get("auto_brightness", self.button.auto_brightness)
            self.button.brightness = button.get("brightness", self.button.brightness)
            if "RGB_COLOR" in self._remote.system.flags.button_features:
                self.button.static_color = button.get("static_color")

        if sound := state.get("sound"):
            self.sound.enabled = sound.get("enabled", self.sound.enabled)
            self.sound.volume = sound.get("volume", self.sound.volume)

        if haptic := state.get("haptic"):
            self.haptic.enabled = haptic.get("enabled", self.haptic.enabled)

        if sw := state.get("software_update"):
            self.software_update.check_for_updates = sw.get(
                "check_for_updates", self.software_update.check_for_updates
            )
            self.software_update.auto_update = sw.get(
                "auto_update", self.software_update.auto_update
            )
            self.software_update.ota_window_start = sw.get(
                "ota_window_start", self.software_update.ota_window_start
            )
            self.software_update.ota_window_end = sw.get(
                "ota_window_end", self.software_update.ota_window_end
            )
            self.software_update.channel = sw.get("channel", self.software_update.channel)

        if ps := state.get("power_saving"):
            self.power_saving.display_off_sec = ps.get(
                "display_off_sec", self.power_saving.display_off_sec
            )
            self.power_saving.wakeup_sensitivity = ps.get(
                "wakeup_sensitivity", self.power_saving.wakeup_sensitivity
            )
            self.power_saving.standby_sec = ps.get("standby_sec", self.power_saving.standby_sec)

        if net := state.get("network"):
            self.network.bt_enabled = bool(net.get("bt_enabled", self.network.bt_enabled))
            self.network.wifi_enabled = bool(net.get("wifi_enabled", self.network.wifi_enabled))
            wifi = net.get("wifi", {})
            if wifi:
                self.network.wifi.band = wifi.get("band", self.network.wifi.band)
                self.network.wifi.scan_interval_sec = wifi.get(
                    "scan_interval_sec", self.network.wifi.scan_interval_sec
                )
                self.network.wifi.ipv4_type = wifi.get("ipv4_type", self.network.wifi.ipv4_type)
            wol = wifi.get("wake_on_wlan") or net.get("wake_on_wlan") or {}
            if wol:
                self.network.wifi.wake_on_wlan = bool(
                    wol.get("enabled", self.network.wifi.wake_on_wlan)
                )

        if loc := state.get("localization"):
            self.localization.language_code = loc.get(
                "language_code", self.localization.language_code
            )
            self.localization.country_code = loc.get("country_code", self.localization.country_code)
            self.localization.time_zone = loc.get("time_zone", self.localization.time_zone)
            self.localization.time_format_24h = bool(
                loc.get("time_format_24h", self.localization.time_format_24h)
            )
            self.localization.measurement_unit = loc.get(
                "measurement_unit", self.localization.measurement_unit
            )

        if bt := state.get("bt"):
            self.bluetooth.peripheral_connections = bt.get(
                "peripheral_connections", self.bluetooth.peripheral_connections
            )
            self.bluetooth.advertisement_name = bt.get(
                "advertisement_name", self.bluetooth.advertisement_name
            )
            self.bluetooth.enable_hci_log = bool(
                bt.get("enable_hci_log", self.bluetooth.enable_hci_log)
            )
            self.bluetooth.enable_debug_port = bool(
                bt.get("enable_debug_port", self.bluetooth.enable_debug_port)
            )
            self.bluetooth.version = bt.get("version", self.bluetooth.version)

        if device := state.get("device"):
            self._remote.device.name = device.get("name", "")

        if profile := state.get("profile"):
            self.profile.has_admin_pin = bool(
                profile.get("has_admin_pin", self.profile.has_admin_pin)
            )

        if voice := state.get("voice"):
            self.voice.microphone = bool(voice.get("microphone", self.voice.microphone))
            self.voice.voice_assistant = voice.get("voice_assistant", self.voice.voice_assistant)

        if features := state.get("features"):
            self.features = [
                Feature(
                    id=f.get("id", ""),
                    enabled=bool(f.get("enabled", False)),
                    title=f.get("title", {}),
                    description=f.get("description", {}),
                    help_url=f.get("help_url", ""),
                )
                for f in features
            ]

        self._remote._last_update_type = UpdateType.CONFIGURATION

    async def _fetch_configuration(self) -> None:
        """Fetch and parse the full ``GET /cfg`` response into ``self.settings``."""
        data = await self._api.get_configuration()

        # Device
        device = data.get("device", {})
        self._remote.device.name = device.get("name", "")

        # Display
        display = data.get("display", {})
        self.display.auto_brightness = bool(display.get("auto_brightness", False))
        self.display.brightness = display.get("brightness", 50)

        # Button
        button = data.get("button", {})
        self.button.auto_brightness = bool(button.get("auto_brightness", False))
        self.button.brightness = button.get("brightness", 50)
        self.button.static_color = button.get("static_color")

        # Sound
        sound = data.get("sound", {})
        self.sound.enabled = bool(sound.get("enabled", True))
        self.sound.volume = sound.get("volume", 50)

        # Haptic
        haptic = data.get("haptic", {})
        self.haptic.enabled = bool(haptic.get("enabled", True))

        # Power saving
        ps = data.get("power_saving", {})
        self.power_saving.display_off_sec = ps.get("display_off_sec", 30)
        self.power_saving.wakeup_sensitivity = ps.get("wakeup_sensitivity", 2)
        self.power_saving.standby_sec = ps.get("standby_sec", 900)

        # Network
        net = data.get("network", {})
        self.network.bt_enabled = bool(net.get("bt_enabled", True))
        self.network.wifi_enabled = bool(net.get("wifi_enabled", True))
        wifi = net.get("wifi", {})
        self.network.wifi.band = wifi.get("band", "auto")
        self.network.wifi.scan_interval_sec = wifi.get("scan_interval_sec", 15)
        self.network.wifi.ipv4_type = wifi.get("ipv4_type", "DHCP")
        # wake_on_wlan can appear at wifi level or network level
        wol = wifi.get("wake_on_wlan") or net.get("wake_on_wlan") or {}
        self.network.wifi.wake_on_wlan = bool(wol.get("enabled", False))
        bt_net = net.get("bt", {})
        self.network.bt_address = bt_net.get("address", "")

        # Software update
        sw = data.get("software_update", {})
        self.software_update.check_for_updates = bool(sw.get("check_for_updates", True))
        self.software_update.auto_update = bool(sw.get("auto_update", False))
        self.software_update.ota_window_start = sw.get("ota_window_start", "02:00:00")
        self.software_update.ota_window_end = sw.get("ota_window_end", "05:00:00")
        self.software_update.channel = sw.get("channel", "STABLE")

        # Localization
        loc = data.get("localization", {})
        self.localization.language_code = loc.get("language_code", "en_US")
        self.localization.country_code = loc.get("country_code", "US")
        self.localization.time_zone = loc.get("time_zone", "UTC")
        self.localization.time_format_24h = bool(loc.get("time_format_24h", True))
        self.localization.measurement_unit = loc.get("measurement_unit", "METRIC")

        # Bluetooth
        bt = data.get("bt", {})
        self.bluetooth.peripheral_connections = bt.get("peripheral_connections", 1)
        self.bluetooth.advertisement_name = bt.get("advertisement_name", "")
        self.bluetooth.enable_hci_log = bool(bt.get("enable_hci_log", False))
        self.bluetooth.enable_debug_port = bool(bt.get("enable_debug_port", False))
        self.bluetooth.version = bt.get("version", "")

        # Profile
        profile = data.get("profile", {})
        self.profile.has_admin_pin = bool(profile.get("has_admin_pin", False))

        # Voice
        voice = data.get("voice", {})
        self.voice.microphone = bool(voice.get("microphone", False))
        self.voice.voice_assistant = voice.get("voice_assistant", {})

        # Features
        self.features = [
            Feature(
                id=f.get("id", ""),
                enabled=bool(f.get("enabled", False)),
                title=f.get("title", {}),
                description=f.get("description", {}),
                help_url=f.get("help_url", ""),
            )
            for f in data.get("features", [])
        ]

    async def update_display(
        self,
        *,
        auto_brightness: bool | None = None,
        brightness: int | None = None,
    ) -> None:
        """Update display settings, patching only the supplied values.

        Args:
            auto_brightness: Enable or disable automatic brightness adjustment.
            brightness: Display brightness level (0-100).
        """
        body: dict = {
            "auto_brightness": self.display.auto_brightness,
            "brightness": self.display.brightness,
        }
        if auto_brightness is not None:
            body["auto_brightness"] = auto_brightness
        if brightness is not None:
            body["brightness"] = brightness
        await self._api.patch_display_settings(body)
        self.display.auto_brightness = bool(body["auto_brightness"])
        self.display.brightness = int(body["brightness"])

    async def update_button(
        self,
        *,
        auto_brightness: bool | None = None,
        brightness: int | None = None,
        static_color: dict | None = None,
    ) -> None:
        """Update button backlight settings.

        Args:
            auto_brightness: Enable or disable automatic button brightness.
            brightness: Button brightness level (0-100).
            static_color: RGB colour dict for static button illumination.
        """
        await self._ensure_awake()
        body: dict = {
            "auto_brightness": self.button.auto_brightness,
            "brightness": self.button.brightness,
        }
        if self.button.static_color is not None:
            body["static_color"] = self.button.static_color
        if auto_brightness is not None:
            body["auto_brightness"] = auto_brightness
        if brightness is not None:
            body["brightness"] = brightness
        if (
            static_color is not None
            and "RGB_COLOR" in self._remote.system.flags.button_features
            and static_color
        ):
            body["static_color"] = static_color
        await self._api.patch_button_settings(body)
        self.button.auto_brightness = bool(body["auto_brightness"])
        self.button.brightness = int(body["brightness"])
        self.button.static_color = body.get("static_color")

    async def update_sound(
        self,
        *,
        enabled: bool | None = None,
        volume: int | None = None,
    ) -> None:
        """Update sound effect settings.

        Args:
            enabled: Enable or disable UI sound effects.
            volume: Sound effects volume level (0-100).
        """
        await self._ensure_awake()
        body: dict = {
            "enabled": self.sound.enabled,
            "volume": self.sound.volume,
        }
        if enabled is not None:
            body["enabled"] = enabled
        if volume is not None:
            body["volume"] = volume
        await self._api.patch_sound_settings(body)
        self.sound.enabled = bool(body["enabled"])
        self.sound.volume = int(body["volume"])

    async def update_haptic(self, *, enabled: bool | None = None) -> None:
        """Enable or disable haptic feedback.

        Args:
            enabled: Enable or disable haptic feedback.
        """
        await self._ensure_awake()
        body: dict = {"enabled": self.haptic.enabled}
        if enabled is not None:
            body["enabled"] = enabled
        await self._api.patch_haptic_settings(body)
        self.haptic.enabled = bool(body["enabled"])

    async def update_power_saving(
        self,
        *,
        display_timeout: int | None = None,
        wakeup_sensitivity: int | None = None,
        sleep_timeout: int | None = None,
    ) -> None:
        """Update power-saving settings.

        Args:
            display_timeout: Seconds before display turns off (0-60).
            wakeup_sensitivity: Wake-up sensitivity level (0-3).
            sleep_timeout: Seconds before entering standby (0-1800).
        """
        await self._ensure_awake()
        body: dict = {
            "display_off_sec": self.power_saving.display_off_sec,
            "wakeup_sensitivity": self.power_saving.wakeup_sensitivity,
            "standby_sec": self.power_saving.standby_sec,
        }
        if display_timeout is not None:
            body["display_off_sec"] = display_timeout
        if wakeup_sensitivity is not None:
            body["wakeup_sensitivity"] = wakeup_sensitivity
        if sleep_timeout is not None:
            body["standby_sec"] = sleep_timeout
        await self._api.patch_power_saving_settings(body)
        self.power_saving.display_off_sec = int(body["display_off_sec"])
        self.power_saving.wakeup_sensitivity = int(body["wakeup_sensitivity"])
        self.power_saving.standby_sec = int(body["standby_sec"])

    async def update_network(
        self,
        *,
        bt_enabled: bool | None = None,
        wifi_enabled: bool | None = None,
        wake_on_wlan: bool | None = None,
    ) -> None:
        """Update network settings.

        Args:
            bt_enabled: Enable or disable Bluetooth.
            wifi_enabled: Enable or disable Wi-Fi.
            wake_on_wlan: Enable or disable Wake-on-WLAN.
        """
        await self._ensure_awake()
        body: dict = {
            "bt_enabled": self.network.bt_enabled,
            "wifi_enabled": self.network.wifi_enabled,
        }
        if bt_enabled is not None:
            body["bt_enabled"] = bt_enabled
        if wifi_enabled is not None:
            body["wifi_enabled"] = wifi_enabled
        if (
            wake_on_wlan is not None
            and self._remote.device.sw_version
            and Version(self._remote.device.sw_version) >= Version("2.0.0")
        ):
            body["wake_on_wlan"] = {"enabled": wake_on_wlan}
        await self._api.patch_network_settings(body)
        self.network.bt_enabled = bool(body["bt_enabled"])
        self.network.wifi_enabled = bool(body["wifi_enabled"])
        if wake_on_wlan is not None:
            self.network.wifi.wake_on_wlan = wake_on_wlan
