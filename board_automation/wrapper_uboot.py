#!/usr/bin/python3

import time
import re
import math


#-------------------------------------------------------------------------------
def get_size_str(size):
    scale_str = 'KMGTPEZY'
    unit = 'Byte'
    factor = 0
    while (size >= 1024):
        size /= 1024
        unit = f'{scale_str[factor]}iB'
        factor += 1
        if factor >= len(scale_str): break
    return f'{size:.1f} {unit}'


#===============================================================================
#===============================================================================

class UBootAutomation():

    #---------------------------------------------------------------------------
    def __init__(self, log, funcWrite):
        self.log = log
        self.funcWrite = funcWrite

    #---------------------------------------------------------------------------
    def intercept_autostart(self):
        # Abort U-Boot start and give us a shell. The message we are waiting for
        # does not have a newline. However, the liner reader has an infinite
        # timeout set. We have to reduce this, so we can get the incomplete
        # line. The log_monitor on the UART run's a loop reading lines with a
        # timeout of 100 ms already, so we can never get below that anyway.
        # Since we know U-Boot will show the prompt almost immediately, we sleep
        # here for a while, and then drain the log. This should hopefully give
        # us the prompt and then we can send a char to intercept the boot.
        self.log.set_timeout(0.5)
        for line in self.log:
            if 'Hit any key to stop autoboot: ' in line:
                break
        else:
            raise Exception('could not stop autoboot')

        self.funcWrite(b'x')
        self.log.flush()


    #---------------------------------------------------------------------------
    def cmd(self, cmd, check_resp=None, timeout=None):

        # Ensure all log data up to now is consumed.
        self.log.flush()
        # Send the command.
        send_cmd = f'{cmd}\n'
        # ToDo: Encoding to 'ascii' seems better than 'utf-8' or 'latin_1'
        #       assuming no special chars are used. The UART monitor uses
        #       'latin_1' when reading. Clarify why this is used to demystify
        #       things a bit more.
        self.funcWrite(bytearray(send_cmd.encode('ascii')))
        # Allow 100ms for general processing if there is no response checking.
        if check_resp is None:
            time.sleep(0.1)
            return
        # Check response.
        ret = self.log.find_matches_in_lines([
            (send_cmd, 1),
            (check_resp, timeout)
        ])
        if not ret.ok:
            raise Exception(f'U-Boot cmd failed, expected: {ret.get_missing()}')


    #---------------------------------------------------------------------------
    def check_env(self, var, value, timeout = 1):
        self.cmd(f'echo ${var}', value, timeout = timeout)


    #---------------------------------------------------------------------------
    def cmd_setenv(self, var, value, timeout = 1):
        self.cmd(f'setenv {var} {value}', timeout = timeout)


    #---------------------------------------------------------------------------
    # We need both 'tftp_img' and 'img_size', because 'tftp_img' is not a local
    # file where we can get the size, but a network location where the board can
    # get it from.
    def cmd_bootelf(self, elf_load_addr):
        # The start address printed is not the load address of the ELF file
        self.cmd(
            f'bootelf {elf_load_addr:#x}',
            '## Starting application at 0x', 3)


    #---------------------------------------------------------------------------
    # We need both 'tftp_img' and 'img_size', because 'tftp_img' is not a local
    # file where we can get the size, but a network location where the board can
    # get it from.
    def cmd_tftp(self, load_addr, server_ip, tftp_img, img_size, board_ip = None):

        # Testing has shown that loading works with a bit over 1 MiByte/s, so
        # calculating a conservative timeout assuming 5 seconds setup time and
        # at least 750 KiByte/s thoughput should be safe.
        tfpt_load_timeout = 5 + math.ceil(img_size / (750*1024))
        #print(f'#### allowing {tfpt_load_timeout} secs for TFTP loading {get_size_str(img_size)} from {img}...')
        load_start = time.time()

        # tftp - load file via network using TFTP protocol
        # Usage: tftp [loadAddress] [[hostIPaddr:]bootfilename]
        # Board must have an IP address, e.g. from 'setenv ipaddr [addr]
        #
        # ToDo: seems the command 'tftpboot' does the same?

        self.cmd(
            f'tftp {load_addr:#x} {server_ip}:{tftp_img}',
            f'TFTP from server {server_ip}; our IP address is {board_ip or ""}', 10)
        ret = self.log.find_matches_in_lines([
            ( re.compile('TFTP error: |done'), tfpt_load_timeout),
        ])

        load_duration = time.time() - load_start
        if not ret.ok:
            raise Exception(f'Loading failed: {ret.get_missing()}')
        if ret.items[0].match == 'TFTP error: ':
            raise Exception(f'TFTP error')

        #print(f'#### loading {get_size_str(img_size)} took {math.ceil(load_duration)} of {tfpt_load_timeout} secs, ' + \
        #      f'throughput: {get_size_str(img_size/load_duration)}/s')

        ret = self.log.find_matches_in_lines([
            ( f'Bytes transferred = {img_size} ({img_size:x} hex)', 1 ),
        ])
        if not ret.ok:
            raise Exception(f'Loading failed: {ret.get_missing()}')


    #---------------------------------------------------------------------------
    def set_board_ip_addr(self, board_ip_addr):
        # The command does not return anything, so we read back the IP address
        # and check it is the new one.
        self.cmd_setenv('ipaddr', board_ip_addr)
        self.check_env('ipaddr', board_ip_addr)


