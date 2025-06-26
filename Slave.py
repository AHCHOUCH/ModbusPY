#!/usr/bin/env python3
import threading
import time
import logging
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext, ModbusSequentialDataBlock
from pymodbus.device import ModbusDeviceIdentification

# Configure logging for the slave
tcore=logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('TankSlave')

# Initialize data: 20 coils, 20 registers
# Coil 0: pump (0=off, 1=on), Coil 1: valve (0=closed,1=open)
# Register 0: water level (0-1000)
store = ModbusSlaveContext(
    di=None,
    co=ModbusSequentialDataBlock(0, [0] * 20),
    hr=ModbusSequentialDataBlock(0, [500] + [0] * 19),
    ir=None
)
context = ModbusServerContext(slaves=store, single=True)

# Device identification metadata
ident = ModbusDeviceIdentification()
ident.VendorName = 'SuricataLab'
ident.ProductCode = 'TANK'
ident.ProductName = 'TankSimulator'

# Simulation parameters
MAX_LEVEL = 1000
MIN_LEVEL = 0
PUMP_RATE = 5    # units per second when pump is ON
DRAIN_RATE = 3   # units per second when valve is OPEN

# Simulation loop: update tank level based on pump/valve state
def simulate_tank():
    last_report = None
    while True:
        coils = store.getValues(1, 0, count=2)
        pump_on = bool(coils[0])
        valve_open = bool(coils[1])
        level = store.getValues(3, 0, count=1)[0]

        # Calculate new level
        delta = (PUMP_RATE if pump_on else 0) - (DRAIN_RATE if valve_open else 0)
        new_level = max(MIN_LEVEL, min(MAX_LEVEL, level + delta))
        store.setValues(3, 0, [new_level])

        # Log current state
        logger.info(f"Pump={'ON' if pump_on else 'OFF'} Valve={'OPEN' if valve_open else 'CLOSED'} Level={new_level}")

        # Log threshold events once
        if new_level == MIN_LEVEL and last_report != 'empty':
            logger.info("Tank Empty – level = 0")
            last_report = 'empty'
        elif new_level == MAX_LEVEL // 2 and last_report != 'half':
            logger.info(f"Tank Half Full – level = {new_level}")
            last_report = 'half'
        elif new_level == MAX_LEVEL and last_report != 'full':
            logger.info(f"Tank Full – level = {new_level}")
            last_report = 'full'
        elif MIN_LEVEL < new_level < MAX_LEVEL:
            last_report = None

        time.sleep(1)

if __name__ == '__main__':
    threading.Thread(target=simulate_tank, daemon=True).start()
    logger.info('Starting Tank Simulator on 0.0.0.0:5020')
    StartTcpServer(context, identity=ident, address=('0.0.0.0', 5020))
