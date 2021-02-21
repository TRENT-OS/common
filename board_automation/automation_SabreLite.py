#!/usr/bin/python3

import time

from . import tools
from . import board_automation
from . import relay_control


#===============================================================================
#===============================================================================

class Relay_Config_SabreLite(relay_control.Relay_Config):

    #---------------------------------------------------------------------------
    def __init__(self, POWER, RESET, SW1_1, SW1_2):

        super().__init__()

        self.POWER = POWER
        self.add_relay_mgr(POWER)

        self.RESET = RESET
        self.add_relay_mgr(RESET)

        self.SW1_1 = SW1_1
        self.add_relay_mgr(SW1_1)

        self.SW1_2 = SW1_2
        self.add_relay_mgr(SW1_2)


#===============================================================================
#===============================================================================

class Automation_SabreLite(object):

    # fuse setting boot: SW1-1 off, SW1-2 off
    # USB boot:          SW1-1 off, SW1-2 on
    # internal boot:     SW1-1 on,  SW1-2 of


    #---------------------------------------------------------------------------
    def __init__(self, relay_config, printer = None):

        self.relay_config = relay_config;
        self.printer      = printer

        # put all relays in a well defined state
        self.relay_config.set_all_off()


    #---------------------------------------------------------------------------
    def print(self, msg):
        if self.printer:
                self.printer.print(msg)


    #---------------------------------------------------------------------------
    def set_boot_mode_fuse_setting(self):
        self.print('set boot mode fuse setting')
        self.relay_config.SW1_1.prepare_state_off()
        self.relay_config.SW1_2.prepare_state_off()
        self.relay_config.apply_state()


    #---------------------------------------------------------------------------
    def set_boot_mode_usb(self):
        self.print('set boot_mode usb')
        self.relay_config.SW1_1.prepare_state_off()
        self.relay_config.SW1_2.prepare_state_on()
        self.relay_config.apply_state()


    #---------------------------------------------------------------------------
    def set_boot_mode_internal(self):
        self.print('set boot_mode internal')
        self.relay_config.SW1_1.prepare_state_on()
        self.relay_config.SW1_2.prepare_state_off()
        self.relay_config.apply_state()


    #---------------------------------------------------------------------------
    def power_on(self):
        self.print('power on')
        self.relay_config.POWER.set_on()


    #---------------------------------------------------------------------------
    def power_off(self):
        self.print('power off')
        self.relay_config.POWER.set_off()


    #---------------------------------------------------------------------------
    def press_reset(self, delay = 0.1):
        self.print('reset')
        self.relay_config.RESET.set_on()
        time.sleep(delay)
        self.relay_config.RESET.set_off()


    #---------------------------------------------------------------------------
    def boot_internal(self):
        self.print('boot internal')
        self.set_boot_mode_internal()
        self.power_on()

        # seems the board starts automatically, so there is no need to press
        # the reset/power button


    #-------------------------------------------------------------------------------
    def boot_usb_download(self):
        self.print('boot usb')
        self.set_boot_mode_usb()
        self.power_on()
        time.sleep(0.3)
        self.press_reset() # do we need this?


#===============================================================================
#===============================================================================

class boardRunner_SabreLite(board_automation.System_Runner):

    #---------------------------------------------------------------------------
    def __init__(self, run_context, board_setup):

        super().__init__(run_context, board_setup)

        self.board = Automation_SabreLite(
                        board_setup.relay_config,
                        run_context.printer)


    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner, nothing special here
    # def do_cleanup(self):


    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner
    def do_start(self, print_log):

        # make sure the board if powered off
        self.board.power_off()
        time.sleep(0.1)

        # setup the SD card
        mp = self.board_setup.sd_wire.switch_to_host_and_mount(timeout_sec = 5)

        self.print('content of {}'.format(mp))
        tools.print_files_from_folder(mp)

        self.board_setup.sd_wire.copy_file_to_card(
            self.run_context.system_image)

        self.board_setup.sd_wire.unmount_and_switch_to_device(timeout_sec = 5)

        # now the board is ready to boot, enable the UART logger and switch
        # the power on
        self.board_setup.log_monitor.start(
            log_file = self.system_log_file.name,
            print_log = print_log)
        time.sleep(0.1)

        self.board.boot_internal()


    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner, nothing special here
    # def do_stop(self):


    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner, ToDo: implement UART
    def get_serial_socket(self):
        return self.board_setup.uart1

