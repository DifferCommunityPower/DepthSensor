#!/usr/bin/env python

from gi.repository import GLib  # pyright: ignore[reportMissingImports]
from pymodbus.client.sync import ModbusSerialClient as ModbusClient
import platform
import logging
import sys
import os
from time import sleep
# import configparser  # for config/ini file
import _thread
import dbus

# import Victron Energy packages
sys.path.insert(1, "/data/SetupHelper/velib_python")
from vedbus import VeDbusService

# formatting
def _litres(p, v):
    return str("%.3f" % v) + "m3"

def _percent(p, v):
    return str("%.1f" % v) + "%"

def _n(p, v):
    return str("%i" % v)

class SystemBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SYSTEM)

class SessionBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SESSION)
        
def dbusconnection():
    return SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else SystemBus()


logging.basicConfig(level=logging.INFO)

log = logging.getLogger("__name__")


# get type Tank #1
tank_type = 0

# get capacity Tank #1
capacity = 100

# get standard Tank #1
standard = 0    


# set variables
connected = 0
level = -999
remaining = None



class DepthSensor:
    def __init__(self):
        self.client = ModbusClient(
            method='rtu',
            port='/dev/ttyUSB0',  # linux
            baudrate=9600,
            timeout=3,
            parity='N',
            stopbits=1,
            bytesize=8
        )
        self.unit_id = 1
        self.tank_depth = 5.0
        self.tank_area = 1.0
        self.scaling_factor = 0.001
        self.unit = "Unknown Unit"  # Store the unit here

    def connect(self):
        # Connect to the Modbus client
        if self.client.connect():
            log.warning("Connected to Modbus client")
            unit_response = self.client.read_holding_registers(0x0002, 1, unit=self.unit_id)

            if not unit_response.isError():
                unit_value = unit_response.registers[0]
                unit_mapping = {
                    0x0000: "MPa",
                    0x0001: "kPa",
                    0x0002: "Pa",
                    0x0003: "bar",
                    0x0004: "mbar",
                    0x0005: "kg/cm²",
                    0x0006: "psi",
                    0x0007: "mH₂O",
                    0x0008: "mmH₂O",
                    0x0009: "°C",
                    0x000A: "cmH₂O"
                }

                #current_unit = unit_mapping.get(unit_value, "Unknown Unit")
                self.unit = unit_mapping.get(unit_value, "Unknown Unit")

                # Read scaling factor
                scaling_response = self.client.read_holding_registers(0x0003, 1, unit=self.unit_id)
                if not scaling_response.isError():
                    scaling_value = scaling_response.registers[0]
                    scaling_factors = {0x0000: 1, 0x0001: 0.1, 0x0002: 0.01, 0x0003: 0.001}
                    self.scaling_factor = scaling_factors.get(scaling_value, 1)
            else:
                log.error("Error reading unit value")
            return True
        return False

    ''' def get_level(self):
        result = self.client.read_holding_registers(0x0004, 1, unit=self.unit_id)
        err = result.isError()
        if not err:
            raw_value = result.registers[0]
            if raw_value == 65534:
                return None
            else:
                level = raw_value * self.scaling_factor
                                    # Calculate percentage of tank filled
                level_percentage = (level / self.tank_depth) * 100  # in percentage
                    
                # Calculate total and remaining volume
                total_volume = self.tank_area * self.tank_depth  # in cubic meters
                current_volume = level * self.tank_area  # in cubic meters
                remaining_volume = total_volume - current_volume  # in cubic meters
                    
                # Convert remaining volume to liters
                remaining_volume_liters = remaining_volume * 1 #1000  # 1 m³ = 1000 liters
                    
                    
                # Prepare JSON output
                log.warning(f"Level: {level_percentage:.2f}%, Remaining Volume: {remaining_volume_liters:.2f} liters")


                return level_percentage, remaining_volume_liters, False

        else:
            log.error("Error reading data from GLT500.")
            return -1, -1, True'''

        
        def get_level(self):
            result = self.client.read_holding_registers(0x0004, 1, unit=self.unit_id)
            err = result.isError()
            if not err:
                raw_value = result.registers[0]
                if raw_value == 65534:
                    return None
                else:
                    # Calculate the raw level with scaling
                    level = raw_value * self.scaling_factor

                    # Log the level with its unit
                    log.warning(f"Level: {level:.2f} {self.unit}")

                    return level, self.unit, False

            else:
                log.error("Error reading data from GLT500.")
                return -1, "Unknown Unit", True





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
        self.last = -2

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
        self._dbusservice.add_path("/FirmwareVersion", "0.0.1 (20241010)")
        # self._dbusservice.add_path('/HardwareVersion', '')
        self._dbusservice.add_path("/Connected", 1)

        self._dbusservice.add_path("/Status", 0)
        self._dbusservice.add_path("/FluidType", tank_type)
        self._dbusservice.add_path("/Capacity", capacity)
        self._dbusservice.add_path("/Standard", standard)

        for path, settings in self._paths.items():
            self._dbusservice.add_path(
                path,
                settings["initial"],
                gettextcallback=settings["textformat"],
                writeable=True,
                onchangecallback=self._handlechangedvalue,
            )
        self._dbusservice.add_path("/Unit", None)  # Initialize it as None

        GLib.timeout_add(5000, self._update)  # pause 1000ms before the next request

    '''def _update(self):
        
        level, remaining, err = self._depthsensor.get_level()
        if err:
            return True
        current = level + remaining

        if self.last != current:
            self._dbusservice["/Level"] = (
                round(level, 1) if level is not None else None
            )
            self._dbusservice["/Remaining"] = (
                round(remaining, 3) if remaining is not None else None
            )

            log_message = "Level: {:.1f} %".format(level)
            log_message += (
                " - Remaining: {:.1f} m3".format(remaining) if remaining is not None else ""
            )
            log.info(log_message)

            self.last = current


        # increment UpdateIndex - to show that new data is available
        index = self._dbusservice["/UpdateIndex"] + 1  # increment index
        if index > 255:  # maximum value of the index
            index = 0  # overflow from 255 to 0
        self._dbusservice["/UpdateIndex"] = index
        return True'''

        #start

    def _update(self):
        level, unit, err = self._depthsensor.get_level()
        if err:
            return True
        current = level  # No need for percentage calculation

        if self.last != current:
            # Update the D-Bus paths with the raw level and unit
            self._dbusservice["/Level"] = round(level, 3) if level is not None else None
            self._dbusservice["/Unit"] = unit  # Add a new path for the unit

            log_message = f"Level: {level:.3f} {unit}"
            log.info(log_message)

            self.last = current

        # Increment UpdateIndex - to show that new data is available
        index = self._dbusservice["/UpdateIndex"] + 1
        if index > 255:
            index = 0
        self._dbusservice["/UpdateIndex"] = index
        return True
    
        #end

    def _handlechangedvalue(self, path, value):
        log.debug("someone else updated %s to %s" % (path, value))
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
            log.info("Waiting 5 seconds for receiving first data...")
        else:
            log.warning(
                "Waiting since %s seconds for receiving first data..." % str(i * 5)
            )
        sleep(5)
        i += 1



    ''' paths_dbus = {
        "/Level": {"initial": None, "textformat": _percent},
        "/Remaining": {"initial": None, "textformat": _litres},
        "/UpdateIndex": {"initial": 0, "textformat": _n},
    }'''

    paths_dbus = {
    "/Level": {"initial": None, "textformat": _n},  # Use raw value formatter
    "/Unit": {"initial": None, "textformat": _n},   # Unit will be stored as a string
    "/UpdateIndex": {"initial": 0, "textformat": _n},
    }



    DbusMqttLevelService(
        servicename="com.victronenergy.tank.well_1",
        deviceinstance=1,
        customname="Well1",
        paths=paths_dbus,
        depthsensor=depthsensor,
    )


    
    log.info(
        "Connected to dbus and switching over to GLib.MainLoop() (= event based)"
    )
    mainloop = GLib.MainLoop()
    mainloop.run()


if __name__ == "__main__":
    main()