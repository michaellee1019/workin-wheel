from __future__ import print_function

import datetime
import argparse
import os.path
import time
import math
# import sys
import random

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as GoogleCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import asyncio

from viam.robot.client import RobotClient
from viam.rpc.dial import Credentials as ViamCredentials, DialOptions
from viam.components.motor import Motor

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

OUT_OF_OFFICE = 0
WORK_FROM_HOME = 1
GOING_TO_EVENT = 2
FOCUS_TIME = 3
AVAILABLE = 4
IN_MEETING = 5

event_type_to_wheel_position = {
    "outOfOffice": 0,
    "focusTime": 3,
    "default": 5, 
}

async def connect(location_secret: str, robot_address: str):
    creds = ViamCredentials(
        type='robot-location-secret',
        payload=location_secret,)
    opts = RobotClient.Options(
        refresh_interval=0,
        dial_options=DialOptions(credentials=creds, timeout=10.0),
        # not available in SDK yet (pending release)
        # timeout=5
    )
    # for x in range(5):
    #     try:
    #         print("connection try", x)
    return await RobotClient.at_address(robot_address, opts)
    #     except Exception as e:
    #         print("Failed to connect", e)
    #         pass
    # raise Exception("Too many connection attempts to robot failed. Please sure that robot is on and connected to wifi.")

def get_next_wheel_position() -> int:
    """Shows basic usage of the Google Calendar API.
    Prints the start and name of the next 10 events on the user's calendar.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json'):
        creds = GoogleCredentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        service = build('calendar', 'v3', credentials=creds)

        # Call the Calendar API
        now = datetime.datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
        print('Getting the upcoming 10 events')
        events_result = service.events().list(calendarId='primary', timeMin=now,
                                              maxResults=1, singleEvents=True,
                                              orderBy='startTime').execute()
        events = events_result.get('items', [])

        if not events:
            print('No upcoming events found.')
            return

        # Prints the start and name of the next 10 events
        # for event in events:
        #     start = event['start'].get('dateTime', event['start'].get('date'))
        #     print(start, event,"\n\n\n")

        event = events[0]
        event_type = event['eventType']
        print("next event type:", event_type)
        start = event['start'].get('dateTime', event['start'].get('date'))
        start_date = datetime.datetime.fromisoformat(start)
        if start_date >= datetime.datetime.now(start_date.tzinfo) + datetime.timedelta(minutes=5):
            print("next event is > 5min from now, so AVAILABLE")
            return AVAILABLE
        elif start_date > datetime.datetime.now(start_date.tzinfo):
            print("next event is <= 5min from now, so GOING_TO_EVENT")
            return GOING_TO_EVENT
        wheel_position = event_type_to_wheel_position.get(event_type)
        return wheel_position

    except HttpError as error:
        print('An error occurred: %s' % error)

async def control_wheel(wheel_motor: Motor, current_wheel_position: int) -> (int, Exception):
    next_wheel_position = get_next_wheel_position() #random.randint(0,5)
    if current_wheel_position != next_wheel_position:
        print("turning wheel from", current_wheel_position, " to position ", next_wheel_position)    
        slices = (current_wheel_position - next_wheel_position)
        dir = math.copysign(1,slices)
        for _ in range(abs(slices)*2):
            await wheel_motor.set_power(-1/12*dir)
            time.sleep(.1)
        return next_wheel_position, None
    return current_wheel_position, None

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--location-secret", required=True, type=str)
    parser.add_argument("--robot-address", required=True, type=str)
    args = parser.parse_args()
    print(args)

    # try:
    print("connecting to robot")
    robot = await connect(args.location_secret, args.robot_address)
    print("turning wheel to initial position 0")
    wheel_motor = Motor.from_robot(robot, "wheel_motor")
    for i in range(12):
        await wheel_motor.set_power(-1/12)
        time.sleep(.1)
    
    current_wheel_position = 0
    while True:
        current_wheel_position, _ = await control_wheel(wheel_motor, current_wheel_position)
        print("wheel now at: ",current_wheel_position)
        time.sleep(15)
        #input()

if __name__ == '__main__':
    asyncio.run(main())