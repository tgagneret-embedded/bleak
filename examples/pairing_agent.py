import argparse
import asyncio

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout

from bleak import BaseBleakAgentCallbacks, BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import (
    BleakDeviceNotFoundError,
    BleakPairingCancelledError,
    BleakPairingFailedError,
)


class AgentCallbacks(BaseBleakAgentCallbacks):
    def __init__(self) -> None:
        self.session: PromptSession[str] = PromptSession()

    async def request_passkey(self, device: BLEDevice) -> str:
        print(f"{device.name} wants to pair.")
        with patch_stdout():
            response = await self.session.prompt_async("enter passkey: ")

        return response

    async def confirm_passkey(self, device: BLEDevice, passkey: str) -> bool:
        print(f"{device.name} wants to pair.")
        with patch_stdout():
            response = await self.session.prompt_async(f"does {passkey} match (y/n)?")

        return response.lower().startswith("y")


async def main(addr: str, unpair: bool, auto: bool) -> None:
    if unpair:
        print("unpairing...")
        try:
            await BleakClient(addr).unpair()
            print("unpaired")
        except BleakDeviceNotFoundError:
            print("device was not paired")

    print("scanning...")

    device = await BleakScanner.find_device_by_address(addr)

    if device is None:
        print("device was not found")
        return

    callbacks = AgentCallbacks()
    if auto:
        print("connecting and pairing...")

        async with BleakClient(
            device, pair=True, pairing_callbacks=callbacks
        ) as client:
            print(f"connection and pairing to {client.address} successful")

    else:
        print("connecting...")

        async with BleakClient(device, pairing_callbacks=callbacks) as client:
            try:
                print("pairing...")
                await client.pair()
                print("pairing successful")
            except BleakPairingCancelledError:
                print("paring was canceled")
            except BleakPairingFailedError:
                print("pairing failed (bad pin?)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser("pairing_agent.py")
    parser.add_argument("address", help="the Bluetooth address (or UUID on macOS)")
    parser.add_argument(
        "--unpair", action="store_true", help="unpair first before pairing"
    )
    parser.add_argument(
        "--auto", action="store_true", help="automatically pair during connect"
    )
    args = parser.parse_args()

    asyncio.run(main(args.address, args.unpair, args.auto))
