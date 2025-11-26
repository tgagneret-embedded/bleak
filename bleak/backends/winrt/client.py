# -*- coding: utf-8 -*-
# Created on 2020-08-19 by hbldh <henrik.blidh@nedomkull.com>
"""
BLE Client for Windows 10 systems, implemented with WinRT.
"""
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    if sys.platform != "win32":
        assert False, "This backend is only available on Windows"

import asyncio
import logging
import uuid
from collections.abc import Callable
from contextvars import Context
from ctypes import WinError
from typing import Any, Generic, Optional, Protocol, Sequence, TypeVar, Union, cast

from warnings import
                warn(
                    "protection_level is deprecated and will be removed in a future version. The default protection level has changed, so it should be safe to omit this argument.",
                    DeprecationWarning,
                    2,
                )
                pairing_result = await custom_pairing.pair_with_protection_level_async(
                    ceremony, protection_level
                )
            else:
                for level in (
                    DevicePairingProtectionLevel.ENCRYPTION_AND_AUTHENTICATION,
                    DevicePairingProtectionLevel.ENCRYPTION,
                ):
                    pairing_result = (
                        await custom_pairing.pair_with_protection_level_async(
                            ceremony, level
                        )
                    )
                    if (
                        pairing_result.status
                        != DevicePairingResultStatus.PROTECTION_LEVEL_COULD_NOT_BE_MET
                    ):
                        break

                    logger.debug("Protection level %r not met. Retrying.", level)
                else:
                    pairing_result = await custom_pairing.pair_async(ceremony)

        except Exception as e:
            raise BleakError("Failure trying to pair with device!") from e
        finally:
            custom_pairing.remove_pairing_requested(pairing_requested_token)

        if pairing_result.status not in (
            DevicePairingResultStatus.PAIRED,
            DevicePairingResultStatus.ALREADY_PAIRED,
        ):
            raise BleakError(
                f"Could not pair with device: {pairing_result.status.name}"
            )

        if logger.isEnabledFor(logging.DEBUG):
            # pairing_result.protection_level_used doesn't seem to return
            # accurate information if we don't update the DeviceInformation
            # first.
            device_information = await DeviceInformation.create_from_id_async(
                self._requester.device_information.id
            )

            logger.debug(
                "Paired to device with protection level %s.",
                pairing_result.protection_level_used.name,
            )

    @override
    async def unpair(self) -> None:
        """Attempts to unpair from the device.

        N.B. unpairing also leads to disconnection in the Windows backend.
        """
        device = await self._create_requester(
            self._device_info
            if self._device_info is not None
            else _address_to_int(self.address)
        )

        try:
            unpairing_result = await device.device_information.pairing.unpair_async()
            if unpairing_result.status not in (
                DeviceUnpairingResultStatus.UNPAIRED,
                DeviceUnpairingResultStatus.ALREADY_UNPAIRED,
            ):
                raise BleakError(
                    f"Could not unpair with device: {unpairing_result.status}"
                )
            logger.info("Unpaired with device.")
        finally:
            device.close()

    # GATT services methods

    async def _get_services(
        self,
        *,
        service_cache_mode: Optional[BluetoothCacheMode] = None,
        cache_mode: Optional[BluetoothCacheMode] = None,
        **kwargs: Any,
    ) -> BleakGATTServiceCollection:
        """Get all services registered for this GATT server.

        Returns:
           A :py:class:`bleak.backends.service.BleakGATTServiceCollection` with this device's services tree.

        """

        # Return the Service Collection.
        if self.services is not None:
            return self.services

        logger.debug(
            "getting services (service_cache_mode=%r, cache_mode=%r)...",
            service_cache_mode,
            cache_mode,
        )

        new_services = BleakGATTServiceCollection()
        services: Sequence[GattDeviceService]

        assert self._requester

        if self._requested_services is None:
            if service_cache_mode is not None:
                result = await FutureLike(
                    self._requester.get_gatt_services_with_cache_mode_async(
                        service_cache_mode
                    )
                )
            else:
                result = await FutureLike(self._requester.get_gatt_services_async())

            services = _ensure_success(
                result,
                "services",
                "Could not get GATT services",
            )
        else:
            services = []
            # REVISIT: should properly dispose services on cancel or protect from cancellation

            for s in self._requested_services:
                if service_cache_mode is not None:
                    result = await FutureLike(
                        self._requester.get_gatt_services_for_uuid_with_cache_mode_async(
                            s, service_cache_mode
                        )
                    )
                else:
                    result = await FutureLike(
                        self._requester.get_gatt_services_for_uuid_async(s)
                    )

                services.extend(
                    _ensure_success(
                        result,
                        "services",
                        "Could not get GATT services",
                    )
                )

        try:
            for service in services:
                if cache_mode is not None:
                    result = await FutureLike(
                        service.get_characteristics_with_cache_mode_async(cache_mode)
                    )
                else:
                    result = await FutureLike(service.get_characteristics_async())

                if result.status == GattCommunicationStatus.ACCESS_DENIED:
                    # Windows does not allow access to services "owned" by the
                    # OS. This includes services like HID and Bond Manager.
                    logger.debug(
                        "skipping service %s due to access denied", service.uuid
                    )
                    continue

                characteristics: Sequence[GattCharacteristic] = _ensure_success(
                    result,
                    "characteristics",
                    f"Could not get GATT characteristics for service {service.uuid} ({service.attribute_handle})",
                )

                serv = BleakGATTService(
                    service, service.attribute_handle, str(service.uuid)
                )
                new_services.add_service(serv)

                for characteristic in characteristics:
                    if cache_mode is not None:
                        result = await FutureLike(
                            characteristic.get_descriptors_with_cache_mode_async(
                                cache_mode
                            )
                        )
                    else:
                        result = await FutureLike(
                            characteristic.get_descriptors_async()
                        )

                    descriptors: Sequence[GattDescriptor] = _ensure_success(
                        result,
                        "descriptors",
                        f"Could not get GATT descriptors for characteristic {characteristic.uuid} ({characteristic.attribute_handle})",
                    )

                    char = BleakGATTCharacteristic(
                        characteristic,
                        characteristic.attribute_handle,
                        str(characteristic.uuid),
                        list(
                            gatt_char_props_to_strs(
                                characteristic.characteristic_properties
                            )
                        ),
                        lambda: self._session.max_pdu_size - 3,
                        serv,
                    )

                    new_services.add_characteristic(char)

                    for descriptor in descriptors:
                        desc = BleakGATTDescriptor(
                            descriptor,
                            descriptor.attribute_handle,
                            str(descriptor.uuid),
                            char,
                        )
                        new_services.add_descriptor(desc)

            return new_services
        except BaseException:
            # Don't leak services. WinRT is quite particular about services
            # being closed.
            logger.debug("disposing service objects")

            # HACK: sometimes GattDeviceService.Close() hangs forever, so we
            # add a delay to give the Windows Bluetooth stack some time to
            # "settle" before closing the services
            await asyncio.sleep(0.1)

            for service in services:
                service.close()
            raise

    # I/O methods

    @override
    async def read_gatt_char(
        self, characteristic: BleakGATTCharacteristic, **kwargs: Any
    ) -> bytearray:
        """Perform read operation on the specified GATT characteristic.

        Args:
            characteristic (BleakGATTCharacteristic): The characteristic to read from.

        Keyword Args:
            use_cached (bool): ``False`` forces Windows to read the value from the
                device again and not use its own cached value. Defaults to ``False``.

        Returns:
            (bytearray) The read data.

        """
        if not self.is_connected:
            raise BleakError("Not connected")

        assert self.services

        use_cached = kwargs.get("use_cached", False)

        gatt_char = cast(GattCharacteristic, characteristic.obj)

        value = bytearray(
            _ensure_success(
                await gatt_char.read_value_with_cache_mode_async(
                    BluetoothCacheMode.CACHED
                    if use_cached
                    else BluetoothCacheMode.UNCACHED
                ),
                "value",
                f"Could not read characteristic handle {characteristic.handle}",
            )
        )

        logger.debug("Read Characteristic %04X : %s", characteristic.handle, value)

        return value

    @override
    async def read_gatt_descriptor(
        self, descriptor: BleakGATTDescriptor, **kwargs: Any
    ) -> bytearray:
        """Perform read operation on the specified GATT descriptor.

        Args:
            descriptor: The descriptor to read from.

        Keyword Args:
            use_cached (bool): `False` forces Windows to read the value from the
                device again and not use its own cached value. Defaults to `False`.

        Returns:
            The read data.

        """
        if not self.is_connected:
            raise BleakError("Not connected")

        assert self.services

        use_cached = kwargs.get("use_cached", False)
        gatt_desc = cast(GattDescriptor, descriptor.obj)

        value = bytearray(
            _ensure_success(
                await gatt_desc.read_value_with_cache_mode_async(
                    BluetoothCacheMode.CACHED
                    if use_cached
                    else BluetoothCacheMode.UNCACHED
                ),
                "value",
                f"Could not read Descriptor value for {descriptor.handle:04X}",
            )
        )

        logger.debug("Read Descriptor %04X : %s", descriptor.handle, value)

        return value

    @override
    async def write_gatt_char(
        self, characteristic: BleakGATTCharacteristic, data: Buffer, response: bool
    ) -> None:
        if not self.is_connected:
            raise BleakError("Not connected")

        buf = WinBuffer(len(data))
        buf.length = buf.capacity

        with memoryview(buf) as mv:
            mv[:] = data

        gatt_char = cast(GattCharacteristic, characteristic.obj)

        _ensure_success(
            await gatt_char.write_value_with_result_and_option_async(
                buf,
                (
                    GattWriteOption.WRITE_WITH_RESPONSE
                    if response
                    else GattWriteOption.WRITE_WITHOUT_RESPONSE
                ),
            ),
            None,
            f"Could not write value {data} to characteristic {characteristic.handle:04X}",
        )

    @override
    async def write_gatt_descriptor(
        self, descriptor: BleakGATTDescriptor, data: Buffer
    ) -> None:
        """Perform a write operation on the specified GATT descriptor.

        Args:
            descriptor: The descriptor to read from.
            data: The data to send (any bytes-like object).

        """
        if not self.is_connected:
            raise BleakError("Not connected")

        assert self.services

        buf = WinBuffer(len(data))
        buf.length = buf.capacity

        with memoryview(buf) as mv:
            mv[:] = data

        gatt_desc = cast(GattDescriptor, descriptor.obj)

        _ensure_success(
            await gatt_desc.write_value_with_result_async(buf),
            None,
            f"Could not write value {data!r} to descriptor {descriptor.handle:04X}",
        )

        logger.debug("Write Descriptor %04X : %s", descriptor.handle, data)

    @override
    async def start_notify(
        self,
        characteristic: BleakGATTCharacteristic,
        callback: NotifyCallback,
        **kwargs: Any,
    ) -> None:
        """
        Activate notifications/indications on a characteristic.

        Keyword Args:
            force_indicate (bool): If this is set to True, then Bleak will set up a indication request instead of a
                notification request, given that the characteristic supports notifications as well as indications.
        """
        winrt_char = cast(GattCharacteristic, characteristic.obj)

        # If we want to force indicate even when notify is available, also check if the device
        # actually supports indicate as well.
        if not kwargs.get("force_indicate", False) and (
            winrt_char.characteristic_properties & GattCharacteristicProperties.NOTIFY
        ):
            cccd = GattClientCharacteristicConfigurationDescriptorValue.NOTIFY
        elif (
            winrt_char.characteristic_properties & GattCharacteristicProperties.INDICATE
        ):
            cccd = GattClientCharacteristicConfigurationDescriptorValue.INDICATE
        else:
            raise BleakError(
                "characteristic does not support notifications or indications"
            )

        loop = asyncio.get_running_loop()

        def handle_value_changed(
            sender: GattCharacteristic, args: GattValueChangedEventArgs
        ) -> None:
            value = bytearray(args.characteristic_value)
            loop.call_soon_threadsafe(callback, value)

        event_handler_token = winrt_char.add_value_changed(handle_value_changed)
        self._notification_callbacks[characteristic.handle] = event_handler_token

        try:
            _ensure_success(
                await winrt_char.write_client_characteristic_configuration_descriptor_with_result_async(
                    cccd
                ),
                None,
                f"Could not start notify on {characteristic.handle:04X}",
            )
        except BaseException:
            # This usually happens when a device reports that it supports indicate,
            # but it actually doesn't.
            if characteristic.handle in self._notification_callbacks:
                event_handler_token = self._notification_callbacks.pop(
                    characteristic.handle
                )
                winrt_char.remove_value_changed(event_handler_token)

            raise

    @override
    async def stop_notify(self, characteristic: BleakGATTCharacteristic) -> None:
        """Deactivate notification/indication on a specified characteristic.

        Args:
            characteristic (BleakGATTCharacteristic): The characteristic to deactivate
                notification/indication on.
        """
        if not self.is_connected:
            raise BleakError("Not connected")

        assert self.services

        gatt_char = cast(GattCharacteristic, characteristic.obj)

        _ensure_success(
            await gatt_char.write_client_characteristic_configuration_descriptor_with_result_async(
                GattClientCharacteristicConfigurationDescriptorValue.NONE
            ),
            None,
            f"Could not stop notify on {characteristic.handle:04X}",
        )

        event_handler_token = self._notification_callbacks.pop(characteristic.handle)
        gatt_char.remove_value_changed(event_handler_token)


T = TypeVar("T")


class FutureLike(Generic[T]):
    """
    Wraps a WinRT IAsyncOperation in a "future-like" object so that it can
    be passed to Python APIs.

    Needed until https://github.com/pywinrt/pywinrt/issues/14
    """

    _asyncio_future_blocking = False

    def __init__(self: Self, op: IAsyncOperation[T]) -> None:
        self._op = op
        self._callbacks: list[Callable[[Self], None]] = []
        self._loop = asyncio.get_running_loop()
        self._cancel_requested = False
        self._result = None

        def call_callbacks() -> None:
            for c in self._callbacks:
                c(self)

        def call_callbacks_threadsafe(
            op: IAsyncOperation[T], status: AsyncStatus
        ) -> None:
            if status == AsyncStatus.COMPLETED:
                # have to get result on this thread, otherwise it may not return correct value
                self._result = op.get_results()

            self._loop.call_soon_threadsafe(call_callbacks)

        op.completed = call_callbacks_threadsafe

    def result(self) -> T:
        if self._op.status == AsyncStatus.STARTED:
            raise asyncio.InvalidStateError

        if self._op.status == AsyncStatus.COMPLETED:
            if self._cancel_requested:
                raise asyncio.CancelledError

            assert self._result

            return self._result

        if self._op.status == AsyncStatus.CANCELED:
            raise asyncio.CancelledError

        if self._op.status == AsyncStatus.ERROR:
            if self._cancel_requested:
                raise asyncio.CancelledError

            error_code = self._op.error_code.value
            raise WinError(error_code)

        assert_never(self._op.status)

    def done(self) -> bool:
        return self._op.status != AsyncStatus.STARTED

    def cancelled(self) -> bool:
        return self._cancel_requested or self._op.status == AsyncStatus.CANCELED

    def add_done_callback(
        self,
        callback: Callable[[Self], None],
        *,
        context: Optional[Context] = None,
    ) -> None:
        self._callbacks.append(callback)

    def remove_done_callback(self, callback: Callable[[Self], None]) -> None:
        self._callbacks.remove(callback)

    def cancel(self, msg: Optional[str] = None) -> bool:
        if self._cancel_requested or self._op.status != AsyncStatus.STARTED:
            return False

        self._cancel_requested = True
        self._op.cancel()

        return True

    def exception(self) -> Optional[Exception]:
        if self._op.status == AsyncStatus.STARTED:
            raise asyncio.InvalidStateError

        if self._op.status == AsyncStatus.COMPLETED:
            if self._cancel_requested:
                raise asyncio.CancelledError

            return None

        if self._op.status == AsyncStatus.CANCELED:
            raise asyncio.CancelledError

        if self._op.status == AsyncStatus.ERROR:
            if self._cancel_requested:
                raise asyncio.CancelledError

            error_code = self._op.error_code.value

            return WinError(error_code)

        assert_never(self._op.status)

    def get_loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def __await__(self):
        if not self.done():
            self._asyncio_future_blocking = True
            yield self  # This tells Task to wait for completion.

        if not self.done():
            raise RuntimeError("await wasn't used with future")

        return self.result()  # May raise too.
