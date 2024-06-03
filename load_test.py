import asyncio
import random
import time
import argparse
import math

from viam.robot.client import RobotClient
from viam.components.motor import Motor


async def connect(api_key, api_key_id, smart_machine_domain):
    opts = RobotClient.Options.with_api_key(
        api_key=api_key,
        api_key_id=api_key_id
    )
    opts.refresh_interval=0
    opts.check_connection_interval=0
    opts.attempt_reconnect_interval=0
    opts.disable_sessions=True
    return await RobotClient.at_address(smart_machine_domain, opts)

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", required=True, type=str)
    parser.add_argument("--api-key-id", required=True, type=str)
    parser.add_argument("--smart-machine-domain", required=True, type=str)
    args = parser.parse_args()

    print("connecting...")
    n_try = 10
    while n_try:
        try:
            smart_machine = await connect(args.api_key, args.api_key_id, args.smart_machine_domain)
            break;
        except Exception as e:
            n_try = n_try - 1;
    if n_try == 0:
        print("cannot connect, exiting")
        exit()

    print("turning wheel to initial position 0")
    for _ in range(6):
        await rotate_with_retry(smart_machine, -1/12)

    current_wheel_position = 0
    while True:
        next_wheel_position = random.randint(0,5)
        if current_wheel_position != next_wheel_position:
            print("turning wheel from", current_wheel_position, " to position ", next_wheel_position)    
            slices = (current_wheel_position - next_wheel_position)
            direction = math.copysign(1,slices)
            for _ in range(abs(slices)*2):
                await rotate_with_retry(smart_machine, -1/12*direction)
            current_wheel_position = next_wheel_position

async def rotate_with_retry(smart_machine: RobotClient, rotations: float):
    try:
        wheel_motor = Motor.from_robot(smart_machine, "wheel_motor")
        await wheel_motor.set_power(rotations)
    except Exception as e:
        print("CUSTOM ATTEMPT to reconnect after exception", e)
        while True:
            try:
                smart_machine = await connect(args.api_key, args.api_key_id, args.smart_machine_domain)
                break
            except Exception as e:
                print("CUSTOM ATTEMPT to reconnect after exception", e)
                continue


if __name__ == '__main__':
    asyncio.run(main())
