#!/usr/bin/env python3

import sys
import os
import time

import board_automation.wrapper_pyftdi
#
## pyftdi needs pyusb
#tools.add_subdir_to_sys_path(__file__, 'pyusb')
#tools.add_subdir_to_sys_path(__file__, 'pyftdi')
#from pyftdi import gpio, ftdi

#-------------------------------------------------------------------------------
def main():
    gpio = board_automation.wrapper_pyftdi.get_pyftdi_gpio('ftdi://ftdi:232h:1/1')

    while True:
        print('off')
        gpio.write(0)
        time.sleep(1)
        print('on')
        gpio.write(1)
        time.sleep(10)


#===============================================================================
#===============================================================================

if __name__ == "__main__":
    main()
