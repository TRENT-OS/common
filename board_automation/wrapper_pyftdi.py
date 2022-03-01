#!/usr/bin/python3

import sys
import os

from . import tools

# pyftdi needs pyusb
tools.add_subdir_to_sys_path(__file__, 'pyusb')
tools.add_subdir_to_sys_path(__file__, 'pyftdi')
import pyftdi
import pyftdi.ftdi
import pyftdi.gpio

#===============================================================================
#===============================================================================

class FTDI_CBUS_GPIO:

    #---------------------------------------------------------------------------
    def __init__(self, url):

        self.ftdi = pyftdi.ftdi.Ftdi()

        self.ftdi.open_from_url(url)

        if not self.ftdi.has_cbus:
            raise Exception('CBUS not available')

        # 4 CBUS pins, all are output
        self.configure(mask=0x0F, direction=0x0F)


    #---------------------------------------------------------------------------
    def configure(self, mask, direction):
        self.ftdi.set_cbus_direction(mask, direction)


    #---------------------------------------------------------------------------
    def write(self, mask):
        self.ftdi.set_cbus_gpio(mask)


    #---------------------------------------------------------------------------
    def read(self):
        return self.ftdi.get_cbus_gpio()


#===============================================================================
#===============================================================================

#-------------------------------------------------------------------------------
# FTDI VID 0x0403
#
#   Device                                          | PID
# --------------------------------------------------+---------
#   FT232BM/L/Q, FT245BM/L/Q, FT232RL/Q, FT245RL/Q  | 0x6001
#   FT2232C/D/L, FT2232HL/Q                         | 0x6010
#   FT4232HL/Q                                      | 0x6011
#   FT232HL/Q                                       | 0x6014
#   FT200XD, FT231X                                 | 0x6015
#
def list_devices(vid = 0x0403):
    def get_id_from_file(dn, id_file):
        id_file_fqn = os.path.join(dn, id_file)
        if not os.path.exists(id_file_fqn): return None
        with open(id_file_fqn) as f: return f.read().strip()

    base_folder = '/sys/bus/usb/devices'
    for usb_path in sorted(os.listdir(base_folder)):
        dn = os.path.join(base_folder, usb_path)
        dev_vid = get_id_from_file(dn, 'idVendor')
        dev_pid = get_id_from_file(dn, 'idProduct')
        dev_ser = get_id_from_file(dn, 'serial')
        if (dev_vid != f'{vid:04x}'): continue
        if dev_ser is None: dev_ser = ''
        print(f'{dev_vid}:{dev_pid} {dev_ser:12} at {usb_path}')


#-------------------------------------------------------------------------------
def get_pyftdi_gpio(url):

    list_devices()
    pyftdi.ftdi.Ftdi.show_devices()

    try:
        pyftdi.ftdi.Ftdi.show_devices()
    except Exception as e:
        print(f'Exception: {e}')

    print(f'opening {url}')
    gpio_contoller = pyftdi.gpio.GpioAsyncController()
    gpio_contoller.configure(url, direction=0xFF)

    return gpio_contoller


#-------------------------------------------------------------------------------
def get_pyftdi_cbus_gpio(url):

    return FTDI_CBUS_GPIO(url)
