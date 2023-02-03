#!/usr/bin/python3

import os
import time

from . import relay_control
from . import sd_wire
from . import uart_reader
from . import wrapper_pyftdi
from . import wrapper_uboot


#===============================================================================
#===============================================================================

class BoardSetup():

    #---------------------------------------------------------------------------
    def __init__(self, printer = None):

        self.printer = printer
        self.gpio = None
        self.sd_wire = None
        self.uarts = []

        self.MAC = '???'

        self.tftp_ip = '10.0.0.31'
        self.tftp_server_ip = '10.0.0.10'

        # UART0 is for syslog
        uart = uart_reader.TTY_USB.find_device(
                        # 10c4:ea60 s/n 0001 at 1-4.2.1.4.1.4, driver cp210x
                        # 1a86:7523 [no s/n] at 1-4.2.1.4.1, driver ch341-uart
                        #serial    = '...',
                        usb_path  = '1-4.2.1.3.3'                     )
        self.uarts.append(uart)

        # ToDo: GPIO setup
        #
        #       use RasPi Pico as USB-UART -> GPIO Adapter based on
        #       https://github.com/Noltari/pico-uart-bridge
        self.gpio = pyftdi.gpio.GpioMpsseController()
        self.gpio.configure(
            url = 'ftdi://ftdi:232h:1/1',
            frequency = 10e6
        )

        # ACBUS[0] as out
        self.gpio.set_direction(pins=0x0100, direction=0x0100)
        self.gpio.write(0x0000)

        #while True:
        #    print('on')
        #    self.gpio.write(0x0100)
        #    time.sleep(1)
        #    print('off')
        #    self.gpio.write(0x0000)
        #    time.sleep(1)


    #---------------------------------------------------------------------------
    def test_cbus(self):
        # Test FTDI C-Bus access
        #
        # pyftdi URL: ftdi://[vendor][:[product][:serial|:bus:address|:index]]/interface
        #
        # LC231X module supports GPIO and CBUS:
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
        #
        #
        # sd-wire uses a FT200XD, the SD card switch is controlled via CBUS0.
        #
        #    # register sd-wire device with pyftdi core, so we can use it
        #    VID = 0x04e8 # SAMSUNG
        #    PID = 0x6001 # FT200XD default is 0x6015. FTDI uses PID 0x6001
        #                 #  for FT232 and FT245
        #    ftdi.Ftdi.add_custom_vendor(VID_SAMSUNG, 'samsung')
        #    ftdi.Ftdi.add_custom_product(VID_SAMSUNG, PID_SD_WIRE, 'sd_wire')
        #
        #    URL = f'ftdi://0x{VID:04x}:0x{PID:04x}:{serial}/1'
        #
        # Notes/Links
        #
        #  seems CBUG is supported by the kernel GPIO driver
        #  https://www.crowdsupply.com/pylo/muart/updates/gpio-interfacing
        #  https://stackoverflow.com/questions/30938991/access-gpio-sys-class-gpio-as-non-root

        from . import wrapper_pyftdi
        import pyftdi
        import pyftdi.ftdi
        import pyftdi.eeprom

        print("devices (1):")
        wrapper_pyftdi.list_devices()
        #print("devices (2, needs root access?):")
        #pyftdi.ftdi.Ftdi.show_devices('ftdi:///?')


        def test_raw(vid, pid, sn):

            # Author: Stefan Agner
            # https://blog.printk.io/2019/04/control-ftdi-cbus-while-tty-is-open
            #
            # Control Transfers for CBUS access are possible without detaching
            # the kernel driver for the USB/UART adapter
            #
            # FTDIs CBUS bitmode expect the following value:
            #   CBUS Bits
            #   3210 3210
            #        |------ Output Control 0->LO, 1->HI
            #   |----------- Input/Output   0->Input, 1->Output
            #
            # PyUSB control endpoint communication, see also:
            # https://github.com/pyusb/pyusb/blob/master/docs/tutorial.rst

            import sys
            import usb

            def ftdi_set_bitmode(dev, bitmask):
                BITMODE_CBUS = 0x20
                SIO_SET_BITMODE_REQUEST = 0x0b

                bmRequestType = usb.util.build_request_type(usb.util.CTRL_OUT,
                                                            usb.util.CTRL_TYPE_VENDOR,
                                                            usb.util.CTRL_RECIPIENT_DEVICE)
                wValue = bitmask | (BITMODE_CBUS << 8)
                dev.ctrl_transfer(bmRequestType, SIO_SET_BITMODE_REQUEST, wValue)

            dev = usb.core.find(custom_match = lambda d: \
                                                  d.idVendor==vid and
                                                  d.idProduct==pid and
                                                  d.serial_number==sn)
            # Set CBUS2/3 high...
            ftdi_set_bitmode(dev, 0xCC)
            time.sleep(1)
            # Set CBUS2/3 low...
            ftdi_set_bitmode(dev, 0xC0)
            # Set CBUS2/3 back to tristate
            ftdi_set_bitmode(dev, 0x00)

        print("FTDI CBUS test_raw")
        test_raw(0x0403, 0x6015, 'FT43WWWA')

        print("FTDI CBUS test URL")

        #URL = 'ftdi://ftdi:232h:1/1'
        URL = 'ftdi://ftdi:ft-x/1'
        #URL = 'ftdi://ftdi:ft-x:FT43WWWA/1' #(LC231X)

        def gpio_cbus(url):
            gpio = wrapper_pyftdi.get_pyftdi_cbus_gpio(url)
            eeprom = pyftdi.eeprom.FtdiEeprom()
            eeprom.connect(gpio.ftdi)
            if (9 != eeprom.cbus_mask):
                print('cbus_pins: ', eeprom.cbus_pins)
                print('cbus_mask: ', eeprom.cbus_mask)
                print('EEPROM:')
                eeprom.dump_config()
                #print('change EEPROM, CBUS[0,3] = GPIO')
                #eeprom.set_property('cbus_func_0', 'GPIO')
                #eeprom.set_property('cbus_func_3', 'GPIO')
                #eeprom.dump_config()
                #eeprom.commit(dry_run=False)
            return gpio

        gpio = gpio_cbus(URL)

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
        #
        # for n in range(0,4):
        #     print(f'{n}')
        #     gpio.write(0)  # set all CBUSx to 0
        #     time.sleep(0.5)
        #     gpio.write(1 << n)  # set CBUSn = 1
        #     #print(f'{gpio.read():x}')
        #     time.sleep(0.2)
        #
        # relay_board = relay_control.Relay_Board(gpio, printer=myPrinter)
        #
        # for n in range(0,8):
        #     print(f'{n}')
        #     self.set_on(n)
        #     time.sleep(0.5)
        #     self.set_on(n)
        #     #self.set_all_off()
        #     time.sleep(0.2)
        #
        # relay_config = relay_control.Relay_Config({
        #                         'POWER': relay_board.get_relay(4),
        #                         'RESET': relay_board.get_relay(5),
        #                         'SW1_1': relay_board.get_relay(6),
        #                         'SW1_2': relay_board.get_relay(7)
        #                     })
        #
        #
        # req_relays = ['POWER', 'RESET', 'SW1_1', 'SW1_2']
        # if not relay_config.check_relays_exist(req_relays):
        #     raise Exception(
        #             'relay configuration invalid, need {}'.format(req_relays))
        #
        # relay_config.set_all_off()
        # relay_config.SW1_1.prepare_state_off()
        # relay_config.SW1_2.prepare_state_off()
        # relay_config.apply_state()


    #---------------------------------------------------------------------------
    def cleanup(self):
        if self.gpio:
            self.gpio.set_direction(pins=0x0000, direction=0x0000)
            self.gpio.close()
        for uart in self.uarts:
            pass # noting to do
        self.sd_wire = None


#===============================================================================
#===============================================================================

class BoardAutomation():

    #---------------------------------------------------------------------------
    def __init__(self, generic_runner, board_setup):
        self.generic_runner = generic_runner
        self.board_setup = board_setup
        self.monitors = []

        uart_syslog = self.get_uart_syslog()
        assert uart_syslog
        monitor = uart_reader.UART_Reader(
                    device  = uart_syslog.device,
                    name    = 'UART0',
                    printer = generic_runner.run_context.printer)
        self.monitors.append(monitor)

        port = monitor.port
        while True:
            port.dtr = 1
            port.rts = 1
            time.sleep(0.2)
            port.dtr = 0
            port.rts = 0
            time.sleep(0.2)


    #---------------------------------------------------------------------------
    def stop(self):
        self.power_off()
        self.stop_system_log()
        for monitor in self.monitors:
            monitor.stop()
        if self.board_setup.sd_wire:
            self.board_setup.sd_wire.switch_to_host()


    #---------------------------------------------------------------------------
    def cleanup(self):
        self.board_setup.cleanup()


    #---------------------------------------------------------------------------
    def print(self, msg):
        printer = self.generic_runner.run_context.printer
        if printer:
            printer.print(msg)

    #---------------------------------------------------------------------------
    def get_uart_syslog(self):
        uarts = self.board_setup.uarts
        if (len(uarts) < 1):
            raise Exception('no uart with syslog')
        return uarts[0]


    #---------------------------------------------------------------------------
    def get_uart_data(self):
        uarts = self.board_setup.uarts
        if (len(uarts) < 2):
            raise Exception('no uart for data')
        return uarts[1]


    #---------------------------------------------------------------------------
    def get_system_log_monitor(self):
        if (len(self.monitors) < 1):
            raise Exception('no syslog monitor')
        return self.monitors[0]


    #---------------------------------------------------------------------------
    def start_system_log(self):
        monitor = self.get_system_log_monitor()
        assert monitor
        monitor.start(
            log_file = self.generic_runner.system_log_file.name,
            print_log = self.generic_runner.run_context.print_log)


    #---------------------------------------------------------------------------
    def stop_system_log(self):
        monitor = self.get_system_log_monitor()
        assert monitor
        monitor.stop()


    #---------------------------------------------------------------------------
    def get_uboot_automation(self, log = None):
        if log is None:
            log = self.generic_runner.get_system_log_line_reader()
        monitor = self.get_system_log_monitor()
        assert monitor
        # It may look a bit odd to write to a monitor, but that is a hack to
        # make things work for now. The monitor has an I/O channel inside, but
        # we need to refactor things to get access to that I/O channel. It would
        # be best if we created the I/O channel and then give it to the monitor
        # and who else needs it, like we do it with the system log stream.
        return wrapper_uboot.UBootAutomation(log, monitor.port.write)


    #---------------------------------------------------------------------------
    def power_on(self):
        self.print('no automation, power on manually')
        self.board_setup.gpio.write(0x0100)
        #self.port.dtr = 0 # it's inverted


    #---------------------------------------------------------------------------
    def power_off(self):
        self.print('no automation, power off manually')
        self.board_setup.gpio.write(0x0000)
        #self.port.dtr = 1 # it's inverted


    #---------------------------------------------------------------------------
    def reset(self, delay = 0.1):
        self.power_off()
        time.sleep(delay)
        self.power_on()

#===============================================================================
#===============================================================================

class BoardRunner():

    #---------------------------------------------------------------------------
    def __init__(self, generic_runner):
        self.data_uart = None

        self.generic_runner = generic_runner
        printer = generic_runner.run_context.printer

        # Get setup for a specific board. The generic_runner.run_context is
        # supposed to contains something that we can use here to pick the right
        # board. For now, there is only one board.
        self.board_setup = BoardSetup(printer)

        # initilaize generic board automation with the specific board
        self.board = BoardAutomation(generic_runner, self.board_setup)


    #---------------------------------------------------------------------------
    def print(self, msg):
        printer = self.generic_runner.run_context.printer
        if printer:
            printer.print(msg)


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def start(self):
        # make sure the board is powered off and then turn it on
        self.board.power_off()
        time.sleep(0.1)

        if self.generic_runner.run_context.use_proxy:
            uart = self.board.get_data_uart()
            self.generic_runner.startProxy(
                connection = f'UART:{uart.device}',
                enable_tap = True,
            )

        self.board.start_system_log()
        log = self.generic_runner.get_system_log_line_reader()
        uboot = self.board.get_uboot_automation(log)

        self.board.power_on()

    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def check_start_board_success(self, log):

        while True:
            self.board_setup.log_monitor.port.dtr = 1
            self.board_setup.log_monitor.port.rts = 1
            time.sleep(0.2)
            self.board_setup.log_monitor.port.dtr = 0
            self.board_setup.log_monitor.port.rts = 0
            time.sleep(0.2)

        test_cbus()


        ret = log.find_matches_in_lines([
            ( [ 'bootloader version:211102-0b86f96' ], 10 ),
            # There is a test running that takes it's time
            ( [ 'crc check PASSED' ], 15 ),
            ( [ 'bootloader.' ], 1),
            ( [ 'OpenSBI v1.0' ], 1),
            ( [ 'Platform Name             : StarFive VisionFive V1' ], 1),
            ( [ 'U-Boot 2022.04-rc2-VisionFive (Mar 07 2022 - 21:12:22 +0800)StarFive' ], 5),
            ( [ 'Model: StarFive VisionFive V1' ], 1),
        ])
        if not ret.ok:
            raise Exception(f'boot string #{len(ret.items)-1} not found: {ret.get_missing()}')

        # Let U-Boot run to the auto start interception prompt and then abort
        # to get us a shell.
        time.sleep(0.5)
        uboot.intercept_autostart()

        # Simple test if U-Boot interaction works. This also checks for a
        # specific version, as this happens to be what we have installed. So
        # any other version is unexpected for now and thus an error.
        uboot.cmd(
            'version',
             'U-Boot 2022.04-rc2-VisionFive (Mar 07 2022 - 21:12:22 +0800)StarFive', 2)

        # some output from "printenv" or "env print":
        #
        #   ... ??? ...

        # Check that our MAC matches
        uboot.check_env('ethaddr', self.board_setup.MAC)

#        # Give the board an IP address for TFTP boot.
#        uboot.set_board_ip_addr(self.board_setup.tftp_ip)
#
#        # This is still a hack, where we have a TFTP server running on the host
#        # and it has a folder 'seos_tests' that points to the same holder on the
#        # host, that is mounted into the docker container at 'host'.
#        # Ideally, we would run our own TFTP server
#        #    https://github.com/mpetazzoni/ptftpd
#        #    https://github.com/sirMackk/py3tftp
#        #
        img = self.generic_runner.run_context.system_image
        img_size = os.path.getsize(img)
#        assert img.startswith('/host/')
#        tftp_img = img.replace('/host/', 'seos_tests/', 1)
#
#        # ToDo: explain why we use this load address
#        elf_load_addr = 0x40000000
#
#        uboot.cmd_tftp(
#            elf_load_addr,
#            self.board_setup.tftp_server_ip,
#            tftp_img,
#            img_size,
#            self.board_setup.tftp_ip)
#
#        uboot.cmd_bootelf(elf_load_addr)
#        time.sleep(0.1)
#        log.flush()


        self.write_uart0(b'loads 0x8590a800\n')
        time.sleep(0.1)
        log.set_timeout(0)
        log.flush()

        #import pathlib
        #img_srec = pathlib.Path(img).with_suffix('.srec')
        (basename, _) = os.path.splitext(img)
        img_srec = f'{basename}.srec'
        if not os.path.exists(img_srec):
            raise Exception(f'missing {img_srec}')

        print(f'loading {img_srec}')
        with open(img_srec, 'rb') as f:
            # file_content = f.read()
            for idx, line in enumerate(f):
                self.write_uart0(line)
                if (0 == idx % 2048): print(idx)
        print('srec done')

        time.sleep(10)
        log.set_timeout(0)
        log.flush()

        # manually upload via ymodem

        # run: picocom --send-cmd="sb -vv" --receive-cmd="rb -vvv" ...
        # in U-Boot use: loady <address>
        # Once it says "## Ready for binary (ymodem) ....." type C-a C-s and
        # choose the file.


        # There is a monitor on UART1, stop it to use the UART for data.
        # self.print('stop monitor for UART1')
        # uart1_monitor = self.board.monitors[1]
        # uart1_monitor.stop_monitor()
        # assert not uart1_monitor.is_monitor_running()
        # self.data_uart = SerialWrapper(uart1_monitor.port)
        # self.print('plat start done')


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def stop(self):
        self.board.stop()
        self.data_uart = None


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def cleanup(self):
        self.stop()
        self.board.cleanup()


    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner: ToDo: implement UART
    def get_serial_socket(self):
        if self.generic_runner.is_proxy_running():
            raise Exception('ERROR: Proxy uses data UART')

        if self.data_uart is None:
            uart = self.board_setup.get_data_uart()
            self.data_uart = SerialWrapper(uart.device, 115200, timeout=1)

        return self.data_uart


#===============================================================================
#===============================================================================

#-------------------------------------------------------------------------------
def get_BoardRunner(generic_runner):
    return BoardRunner(generic_runner)
