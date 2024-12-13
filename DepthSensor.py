#!/usr/bin/env python

from gi.repository import GLib  # pyright: ignore[reportMissingImports]
from pymodbus.client.sync import ModbusSerialClient as ModbusClient
import platform
import logging
import sys
import os
from time import sleep
import glob #new add
import _thread
import dbus
from pymodbus.constants import Defaults
from utils import *

Defaults.Timeout = 5

# import Victron Energy packages
sys.path.insert(1, "/data/SetupHelper/velib_python")
from vedbus import VeDbusService


class SystemBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SYSTEM)

class SessionBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SESSION)
        
def dbusconnection():
    return SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else SystemBus()


logging.basicConfig(level=logging.INFO)

log = logging.getLogger(__name__)


# set variables
connected = 0
level = -999
remaining = None

class DepthSensor:
    def __init__(self):
        self.unit_id = 1
        self.scaling_factor = 0.1
        self.version = getVersion()
        self.connect()

    def scaling(self):
        unit_response = self.client.read_holding_registers(0x0002, 1, unit=self.unit_id)

        if not unit_response.isError():
            unit_value = unit_response.registers[0]
            current_unit = UNIT_MAPPING.get(unit_value, "Unknown Unit")

            # Read scaling factor
            scaling_response = self.client.read_holding_registers(0x0003, 1, unit=self.unit_id)
            if not scaling_response.isError():
                scaling_value = scaling_response.registers[0]
                scaling_factors = {0x0000: 1, 0x0001: 0.1, 0x0002: 0.01, 0x0003: 0.001}
                self.scaling_factor = scaling_factors.get(scaling_value, 1)
                return True
        else:
            log.error("Error reading unit value")
        return False

    def connect(self):
        port = find_port("FTDI")
        if not port:
            log.error("No FTDI device found.")
            return False
        self.client = ModbusClient(
            method='rtu',
            port=port,
            baudrate=9600,
            timeout=3,
            parity='N',
            stopbits=1,
            bytesize=8
        )
        if self.client.connect():
            if self.scaling():
                log.info(f"Connected to Modbus port: {port}")
                return True
            else:
                log.warning(f"Scaling failed, device not likely a Depthsensor")
        else:
            log.error("connect failed")
        return False

    def get_level(self):
        result = self.client.read_holding_registers(0x0004, 1, unit=self.unit_id)
        err, level = result.isError(), -1
        if not err:
            raw_value = result.registers[0]
            level = raw_value * self.scaling_factor
            log.info(f"Level: {level:.2f}m")
        else:
            log.error("Error reading data from GLT500.")
        return level, err

class DbusMqttLevelService:
    def __init__(
        self,
        servicename,
        deviceinstance,
        paths,
        depthsensor: DepthSensor,
        productname="DCP Well Level",
        customname="DCP Well Level",
        connection="DCP Well Level service"): 
        self._depthsensor = depthsensor 
        self._dbusservice = VeDbusService(servicename,dbusconnection())
        self._paths = paths
        self.last = -1

        logging.info("Starting DepthSensor Service")
        logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path("/Mgmt/ProcessName", __file__)
        self._dbusservice.add_path(
            "/Mgmt/ProcessVersion",
            "Unkown version, and running on Python " + platform.python_version(),
        )
        self._dbusservice.add_path("/Mgmt/Connection", connection)

        # Create the mandatory objects
        self._dbusservice.add_path("/DeviceInstance", deviceinstance)
        self._dbusservice.add_path("/ProductId", 0xFFFF)
        self._dbusservice.add_path("/ProductName", productname)
        self._dbusservice.add_path("/CustomName", customname)
        self._dbusservice.add_path("/FirmwareVersion", self._depthsensor.version)
        self._dbusservice.add_path("/Connected", 1)
        self._dbusservice.add_path("/Status", 0)
        self._dbusservice.add_path("/FluidType", TANK_TYPE)
        self._dbusservice.add_path("/Capacity", TANK_CAPACITY)
        self._dbusservice.add_path("/Standard", TANK_STANDARD)

        for path, settings in self._paths.items():
            self._dbusservice.add_path(
                path,
                settings["initial"],
                gettextcallback=settings["textformat"],
                writeable=True,
                onchangecallback=self._handlechangedvalue,
            )

        GLib.timeout_add(SAMPLE_INTERVAL * 1000, self._update)  # pause 1000 x SAMPLE_INTERVAL ms before the next request

    def _update(self):
        
        level, err = self._depthsensor.get_level()
        if err:
            return True
           
        if round(self.last, 2) != round(level, 2):
            self._dbusservice["/Level"] = round(level, 2) if level else None
            self._dbusservice["/Remaining"] = round(level, 3) if level else None
            self.last = level
            log.info("Updated level: {:.2f} m".format(level))


        # increment UpdateIndex - to show that new data is available
        index = self._dbusservice["/UpdateIndex"] + 1  # increment index
        if index > 255:  # maximum value of the index
            index = 0  # overflow from 255 to 0
        self._dbusservice["/UpdateIndex"] = index
        return True

    def _handlechangedvalue(self, path, value):
        log.warning("someone else updated %s to %s" % (path, value))
        return True  # accept the change
    
def main():
    global level, remaining
    _thread.daemon = True  # allow the program to quit

    from dbus.mainloop.glib import (  # pyright: ignore[reportMissingImports]
        DBusGMainLoop,
    )

    # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
    DBusGMainLoop(set_as_default=True)

    # wait to receive first data, else the JSON is empty and phase setup won't work
    i = 0
    depthsensor= DepthSensor()
    connected = False
    while level == -1:
        connected = depthsensor.connect()
        if connected:
            level, remaining, err = depthsensor.get_level()
        if i % 12 != 0 or i == 0:
            log.error("Waiting 5 seconds for receiving first data...")
        else:
            log.warning(
                "Waiting since %s seconds for receiving first data..." % str(i * 5)
            )
        sleep(5)
        i += 1

    paths_dbus = {
        "/Level": {"initial": None, "textformat": format_percent},
        "/Remaining": {"initial": None, "textformat": format_litres},
        "/UpdateIndex": {"initial": 0, "textformat": format_n},
    }


    DbusMqttLevelService(
        servicename="com.victronenergy.tank.well_1",
        deviceinstance=1,
        customname="Well",
        paths=paths_dbus,
        depthsensor=depthsensor,
    )
    
    log.error("Connected to dbus and switching over to GLib.MainLoop() (= event based)" )
    mainloop = GLib.MainLoop()
    mainloop.run()


if __name__ == "__main__":
    main()