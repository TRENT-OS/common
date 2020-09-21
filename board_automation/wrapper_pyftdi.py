#!/usr/bin/python3

import sys
import os
#import pathlib

from . import tools

# pyftdi needs pyusb
tools.add_subdir_to_sys_path(__file__, 'pyusb')
tools.add_subdir_to_sys_path(__file__, 'pyftdi')
from pyftdi import gpio, ftdi


#-------------------------------------------------------------------------------
def get_pyftdi_gpio(url):

    # FTDI VID 0x0403
    #
    #   Device                                          | PID
    # --------------------------------------------------+---------
    #   FT232BM/L/Q, FT245BM/L/Q, FT232RL/Q, FT245RL/Q  | 0x6001
    #   FT2232C/D/L, FT2232HL/Q                         | 0x6010
    #   FT4232HL/Q                                      | 0x6011
    #   FT232HL/Q                                       | 0x6014
    #

    def get_id_from_file(dn, id_file):
        id_file_fqn = os.path.join(dn, id_file)
        if not os.path.exists(id_file_fqn): return None
        with open(id_file_fqn) as f: return f.read().strip()

    base_folder = '/sys/bus/usb/devices'
    for usb_path in sorted(os.listdir(base_folder)):
         dn = os.path.join(base_folder, usb_path)
         vid = get_id_from_file(dn, 'idVendor')
         pid = get_id_from_file(dn, 'idProduct')
         ser = get_id_from_file(dn, 'serial')
         if (vid != '0403'): continue
         print('{}:{} {:12} at {}'.format(vid, pid, ser or '', usb_path))


    ftdi.Ftdi.show_devices()
    print('opening {}'.format(url))


    gpio_contoller = gpio.GpioAsyncController()

    gpio_contoller.configure(url, direction=0xFF)

    return gpio_contoller
