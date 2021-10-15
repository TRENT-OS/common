#!/usr/bin/python3

import time
import os
import subprocess
from enum import IntEnum
from pathlib import Path
from pytest_testconfig import config
import pytest

from . import board_automation


#===============================================================================
#===============================================================================

class Automation(object):

    #---------------------------------------------------------------------------
    def __init__(self, log_dir, printer):

        # Get the variables from a platform-specific configuration file passed to
        # pytest-testconfig. In case the keys don't exist in the config file or the
        # variables have invalid types/values, raise an exception and stop the test
        # execution
        try:
            self.flash_start            = int(config['platform']['flash_start'], 16)
            self.flash_sec_size         = int(config['platform']['flash_sec_size'])
            self.flash_sec_num          = int(config['platform']['flash_sec_num'])
            self.flash_ctrl_reg         = int(config['platform']['flash_ctrl_reg'], 16)
            self.flash_write_align      = int(config['platform']['flash_write_align'])
            self.rom_ctrl_reg           = int(config['platform']['rom_ctrl_reg'], 16)
            self.otp_idx_reg            = int(config['platform']['otp_idx_reg'], 16)
            self.otp_prog_reg           = int(config['platform']['otp_prog_reg'], 16)
            self.otp_prog_idx_offset    = int(config['platform']['otp_prog_idx_offset'])
            self.otp_prog_cmd           = int(config['platform']['otp_prog_cmd'], 16)

            self.remote_access_ip       = config['remote_access']['remote_access_ip']
            self.remote_access_username = config['remote_access']['remote_access_username']
            self.remote_access_key      = next(Path(os.getcwd()).parent.parent.rglob(
                                            config['remote_access']['remote_access_key']))

            self.remote_power_utility   = config['remote_access']['remote_power_utility']
            self.remote_sd_card_utility = config['remote_access']['remote_sd_card_utility']
            self.board_id               = config['remote_access']['board_id']

            self.fpga_cfg               = config['remote_access']['fpga_cfg']
            self.sec_chip_cfg           = config['remote_access']['sec_chip_cfg']
            self.test_ctrl_cfg          = config['remote_access']['test_ctrl_cfg']

            self.gdb_port               = config['remote_access']['gdb_port']
            self.uart_device_id         = config['remote_access']['uart_device_id']
            self.uart_baud_rate         = config['platform']['uart_baud_rate']

            self.board_output_log       = config['resources']['board_output_log']
        except:
            pytest.fail("Parsing platform configuration failed!")

        self.log_dir                = log_dir
        self.screen_session         = 'serial_{}'.format(time.time())

        # Since the OTP values are received in 32-bit register values (for QEMU
        # compatibility), we need to keep track of the number of these values to
        # correctly assign the fuse index and not to overwrite the values
        self.otp_val_cnt            = 0

        self.printer      = printer


    #---------------------------------------------------------------------------
    def print(self, msg):
        if self.printer:
            self.printer.print(msg)


    #---------------------------------------------------------------------------
    def execute_ssh_command(self, cmd, name):
        with open('{}/{}_out.txt'.format(self.log_dir, name), 'w') as fout:
            with open('{}/{}_err.txt'.format(self.log_dir, name), 'w') as ferr:
                # Even though the key authenticates us as root, it is a good
                # idea to change the user to jenkins.
                process = subprocess.Popen(
                    "ssh -i {} {}@{} -f 'su jenkins && {}'".
                        format(self.remote_access_key,
                            self.remote_access_username,
                            self.remote_access_ip,
                            cmd),
                            shell=True,
                            stdout=fout,
                            stderr=ferr)

        return process


    #---------------------------------------------------------------------------
    def power_on(self):
        self.execute_ssh_command('{} {} on'.format(
            self.remote_power_utility,
            self.board_id
        ),
        'power_on')


    #---------------------------------------------------------------------------
    def power_off(self):
        self.execute_ssh_command('{} {} off'.format(
            self.remote_power_utility,
            self.board_id
        ),
        'power_off')


    #---------------------------------------------------------------------------
    def reset(self):
        self.execute_ssh_command('{} {} reset'.format(
            self.remote_power_utility,
            self.board_id
        ),
        'reset')


    #---------------------------------------------------------------------------
    def switch_sd_card_board(self):
        self.execute_ssh_command('{} {} d'.format(
            self.remote_sd_card_utility,
            self.board_id
        ),
        'sd_card_board')


    #---------------------------------------------------------------------------
    def switch_sd_card_host(self):
        self.execute_ssh_command('{} {} s'.format(
            self.remote_sd_card_utility,
            self.board_id
        ),
        'sd_card_host')


    #---------------------------------------------------------------------------
    def start_openocd(self):
        cnt = 0
        self.print('trying to start openocd')
        openocd_proc = self.execute_ssh_command(
                            'openocd -f {} -f {} -f {}'.format(
                                self.fpga_cfg,
                                self.sec_chip_cfg,
                                self.test_ctrl_cfg
                            ),
                            'openocd')
                        
        time.sleep(1)

        # If openocd failed the first time, re-try for up to 3 more times, since
        # the most likely reason for the failure is that the board was not yet
        # ready.
        while cnt < 3:
            with open('{}/openocd_err.txt'.format(self.log_dir), 'r') as ferr:
                log_data = ferr.read()
                if 'Error:' in log_data in log_data:
                    self.print('Openocd failed! Retrying...')

                    # If openocd failed to launch the safest thing is to kill
                    # openocd, reset the board and try again
                    openocd_proc.kill()
                    self.execute_ssh_command('pkill -9 openocd', 'kill_openocd')
                    self.reset()

                    time.sleep(30)

                    openocd_proc = self.execute_ssh_command(
                                        'openocd -f {} -f {} -f {}'.format(
                                            self.fpga_cfg,
                                            self.sec_chip_cfg,
                                            self.test_ctrl_cfg
                                        ),
                                        'openocd')
                    time.sleep(1)

                    cnt += 1
                else:
                    self.print('Openocd started succesfully')
                    break

        return openocd_proc


    #---------------------------------------------------------------------------
    def pad_binary(self, binary):
        # Binary needs to be 32-bit aligned in order for the flash write to
        # be succesful
        img_size = os.path.getsize(binary)

        if img_size % self.flash_write_align:
            with open(binary, 'r+b') as img_file:
                padding_len = self.flash_write_align - (img_size % self.flash_write_align)
                img_file.seek(0, os.SEEK_END)
                img_file.write(b'\x00' * padding_len)


    #---------------------------------------------------------------------------
    def store_binary_to_flash_cmd(self, addres, binary):
        cmd = ""
        # Flash write needs to be 32-bit aligned so it is necessary to pad
        # the image with 0 to the nearest 32-bit alignement
        self.pad_binary(binary)

        begin_sec_id = (addres - self.flash_start)//self.flash_sec_size

        # Erase enough sectors for the kernel binary
        for sec in range(begin_sec_id,
                            begin_sec_id +
                            os.path.getsize(binary)//self.flash_sec_size + 1):

            # Multiplying the sector id with 2^16 shifts it to the correct
            # position (starting from bit 16)
            cmd += " -ex"
            cmd += " 'set {{int}}{} = {}'".format(
                                            self.flash_ctrl_reg,
                                            sec * pow(2,16) + 1)

        #-----------------------------------------------------------------------
        cmd += " -ex"
        cmd += " 'restore {} binary {}'".format(binary, addres)

        return cmd


    #---------------------------------------------------------------------------
    def program_otp_fuses_cmd(self, otp_fuse_list):
        cmd = ""

        for idx, fuse in enumerate(otp_fuse_list, start=0):
            if otp_fuse_list[idx] == '1':
                total_idx = idx + (self.otp_val_cnt * 32)
                cmd += " -ex"
                cmd += " 'set {{int}}{} = {}'".format(self.otp_idx_reg, total_idx)
                cmd += " -ex"
                cmd += " 'set {{int}}{} = {}'".format(
                            self.otp_prog_reg,
                            (~total_idx << self.otp_prog_idx_offset |
                            self.otp_prog_cmd))

        self.otp_val_cnt += 1
        return cmd


    #---------------------------------------------------------------------------
    class Additional_Param_Type(IntEnum):
        VALUE       = 0,
        BINARY_IMG  = 1,


    #---------------------------------------------------------------------------
    def create_gdb_cmd(self, system_img, params):
        gdb_cmd = "/opt/hc/riscv-toolchain/bin/riscv64-unknown-linux-gnu-gdb"
        gdb_cmd += " -ex"
        gdb_cmd += " 'target extended-remote {}:{}'".format(
                        self.remote_access_ip, self.gdb_port)

        if params:
            for param in params:
                if param[2] == self.Additional_Param_Type.VALUE:
                    if self.otp_val_cnt < 2:
                        otp_fuses_bin = '{}'.format(bin(int(param[1], 16)).zfill(8))
                        otp_fuses_lst = [char for char in otp_fuses_bin][2:]
                        otp_fuses_lst.reverse()

                        gdb_cmd += self.program_otp_fuses_cmd(otp_fuses_lst)
                    else:
                        self.print('ZCU102: only 2 additional parameters \
                                of type VALUE supported (32-bit OTP registers)! \
                                Ignoring additional parameter: {} {}'.format(
                                    param[0], param[1]))

                elif param[2] == self.Additional_Param_Type.BINARY_IMG:
                    gdb_cmd += self.store_binary_to_flash_cmd(param[0], param[1])

                else:
                    self.print('ZCU102: additional parameter type {} \
                            not supported!'.format(param[2]))

        gdb_cmd += " -ex"
        gdb_cmd += " 'set {{int}}{} = 1'".format(self.rom_ctrl_reg)
        gdb_cmd += " -ex"
        gdb_cmd += " load {}".format(system_img)
        gdb_cmd += " -ex"
        gdb_cmd += " 'set {{int}}{} = 0'".format(self.rom_ctrl_reg)
        gdb_cmd += " -ex"
        gdb_cmd += " 'c'"

        return gdb_cmd


    #---------------------------------------------------------------------------
    def start_gdb(self, system_img, params):
        gdb_cmd = self.create_gdb_cmd(system_img, params)

        with open('{}/gdb_out.txt'.format(self.log_dir), 'w') as fout:
            with open('{}/gdb_err.txt'.format(self.log_dir), 'w') as ferr:
                process_gdb = subprocess.Popen(
                                gdb_cmd,
                                shell=True,
                                stdout=fout,
                                stderr=ferr)

        return process_gdb


    #---------------------------------------------------------------------------
    def start_serial_capture(self):
        # We start a screen session on the remote test controller in detached
        # mode (-dmS) and start a picocom instance in it, since picocom requires
        # a live terminal. The picocom logs all captured data to the
        # "board_output_log" file which is later parsed by the test case.
        return self.execute_ssh_command(
                'screen -dmS {} bash && \
                 screen -S {} -X stuff "picocom -b 115200 {} -g {}\n"'.format(
                    self.screen_session,
                    self.screen_session,
                    self.uart_device_id, 
                    self.board_output_log                         
                ), 'serial')


    #---------------------------------------------------------------------------
    def extract_log(self):
        # Copy the log file from the remote test controller
        subprocess.run(
            "scp -i {} {}@{}:{} {}/log.txt".
                format(self.remote_access_key,
                        self.remote_access_username,
                        self.remote_access_ip,
                        self.board_output_log,
                        self.log_dir),
                        shell=True)

        # Remove controll characters from the log file for the log parser to be
        # able to succesfully parse the test output (the raw log contains null
        # characters after each char since we directly copy the contents of
        # /dev/tty... to the log.txt)
        with open('{}/log.txt'.format(self.log_dir), 'rb') as log_file:
            with open('{}/guest_out.txt'.format(self.log_dir), 'wb') as new:
                data = log_file.read()
                new.write(data.replace(b'\x00', b'').replace(b'\r', b''))


    #---------------------------------------------------------------------------
    def cleanup(self):
        # Kill used processes on the remote test controller, remove the log file
        # and power off the board
        self.execute_ssh_command('pkill -9 openocd', 'kill_openocd')
        time.sleep(0.5)
        self.execute_ssh_command('pkill -9 minicom', 'kill_serial_capture')
        time.sleep(0.5)
        self.execute_ssh_command('screen -S {} -X quit'.format(self.screen_session), 'kill_screen')
        time.sleep(0.5)
        self.execute_ssh_command('rm -f {}'.format(self.board_output_log), 'remove_log')
        time.sleep(0.5)
        self.power_off()

        # Kill gdb on the host
        subprocess.run("pkill -9 riscv64-unknown-linux-gnu-gdb", shell=True)


#===============================================================================
#===============================================================================

class BoardRunner(board_automation.System_Runner):

    #---------------------------------------------------------------------------
    def __init__(self, run_context, aditional_params):

        super().__init__(run_context, None)
        self.board = Automation(self.run_context.log_dir, run_context.printer)
        self.aditional_params = aditional_params


    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner
    def do_start(self, print_log):
        self.board.switch_sd_card_board()

        time.sleep(1)
        self.board.reset()

        time.sleep(30)
        self.process_serial_capture = self.board.start_serial_capture()

        time.sleep(1)
        self.process_openocd = self.board.start_openocd()

        time.sleep(1)
        self.process_gdb = self.board.start_gdb(
                        self.run_context.system_image,
                        self.aditional_params)

        time.sleep(10)
        self.board.extract_log()


    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner
    def do_cleanup(self):
        self.process_serial_capture.kill()
        self.process_openocd.kill()
        self.process_gdb.kill()

        self.board.cleanup()

