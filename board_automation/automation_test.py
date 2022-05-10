#!/usr/bin/python3

import time
from . import relay_control
from . import wrapper_pyftdi

import pyftdi
import pyftdi.ftdi
import pyftdi.eeprom


#-------------------------------------------------------------------------------
def main():

    class MyPrinter:
        def print(self, msg):
            print(msg)
    myPrinter = MyPrinter()

    print("devices (1):")
    wrapper_pyftdi.list_devices()

    print("devices (2):")
    pyftdi.ftdi.Ftdi.show_devices('ftdi:///?')

    print("test:")

    # # sd-wire uses a FT200XD, the SD card switch is controlled via CBUS0.
    # VID = 0x04e8 # SAMSUNG
    # PID = 0x6001 # FT200XD default is 0x6015. FTDI uses PID 0x6001
    #                      #  for FT232 and FT245
    # # register sd-wire device with pyftdi core, so we can use it
    # ftdi.Ftdi.add_custom_vendor(VID_SAMSUNG, 'samsung')
    # ftdi.Ftdi.add_custom_product(VID_SAMSUNG, PID_SD_WIRE, 'sd_wire')
    #

    # URL = f'ftdi://0x{VID:04x}:0x{PID:04x}:{serial}/1'


    #URL = 'ftdi://ftdi:232h:1/1'
    #gpio = wrapper_pyftdi.get_pyftdi_gpio(URL)

    #URL = 'ftdi://ftdi:ft-x:FT43WWTH/1' #(LC231X)
    #URL = 'ftdi://ftdi:ft-x:FT43WWWA/1' #(LC231X)
    URL = 'ftdi://ftdi:ft-x/1'

    # LC231X module support GPIO and CBUS:
    #   CBUS[0]: default EEPROM setting is TRISTATE, can become GPIO
    #   CBUS[1]: LED (RX)
    #   CBUS[2]: LED (TX)
    #   CBUS[3]: default EEPROM setting is TRISTATE, can become GPIO
    #   TXD:     GPIO_0
    #   RXD:     GPIO_1
    #   RTS:     GPIO_2
    #   CTS:     GPIO_3
    #   DTR:     GPIO_4
    #   DSR:     GPIO_5
    #   DCD:     GPIO_6
    #   RI :     GPIO_7

    def gpio_cbus(url):
        gpio = wrapper_pyftdi.get_pyftdi_cbus_gpio(url)
        eeprom = pyftdi.eeprom.FtdiEeprom()
        eeprom.connect(gpio.ftdi)
        if (9 != eeprom.cbus_mask):
            print('cbus_pins: ', eeprom.cbus_pins)
            print('cbus_mask: ', eeprom.cbus_mask)
            print('EEPROM:')
            eeprom.dump_config()
            print('change EEPROM, CBUS[0,3] = GPIO')
            eeprom.set_property('cbus_func_0', 'GPIO')
            eeprom.set_property('cbus_func_3', 'GPIO')
            #eeprom.dump_config()
            #eeprom.commit(dry_run=False)
        return gpio

    gpio = gpio_cbus(URL)
    #gpio = wrapper_pyftdi.get_pyftdi_gpio(URL)

    #gpio.ftdi.set_cbus_direction(mask=0xf, direction=0x0)
    #print(f'read 0x{gpio.ftdi.get_cbus_gpio():x}')
    #gpio.ftdi.set_cbus_direction(mask=0xf, direction=0xf)
    #gpio.ftdi.set_cbus_gpio(0xf)

    while True:
        print('.')
        gpio.write(0)
        time.sleep(3)
        gpio.write(0xF)
        time.sleep(0.3)


    #for n in range(0,4):
    #    print(f'{n}')
    #    gpio.write(0)  # set all CBUSx to 0
    #    time.sleep(0.5)
    #    gpio.write(1 << n)  # set CBUSn = 1
    #    #print(f'{gpio.read():x}')
    #    time.sleep(0.2)


    #relay_board = relay_control.Relay_Board(gpio, printer=myPrinter)

    #for n in range(0,8):
    #    print(f'{n}')
    #    self.set_on(n)
    #    time.sleep(0.5)
    #    self.set_on(n)
    #    #self.set_all_off()
    #    time.sleep(0.2)

    #relay_config = relay_control.Relay_Config({
    #                        'POWER': relay_board.get_relay(4),
    #                        'RESET': relay_board.get_relay(5),
    #                        'SW1_1': relay_board.get_relay(6),
    #                        'SW1_2': relay_board.get_relay(7)
    #                    })
    #
    #
    #req_relays = ['POWER', 'RESET', 'SW1_1', 'SW1_2']
    #if not relay_config.check_relays_exist(req_relays):
    #    raise Exception(
    #            'relay configuration invalid, need {}'.format(req_relays))
    #
    #relay_config.set_all_off()
    #relay_config.SW1_1.prepare_state_off()
    #relay_config.SW1_2.prepare_state_off()
    #relay_config.apply_state()




#-------------------------------------------------------------------------------
# run as: python3 -m board_automation.automation_test
# running python3 automation_test.py will rause abn error
if __name__ == "__main__":
    main()
