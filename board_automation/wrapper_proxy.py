#!/usr/bin/python3

import os
from . import process_tools


#===============================================================================
#===============================================================================

class Proxy():

    #---------------------------------------------------------------------------
    def __init__(self, binary, printer = None):

        self.process = None
        self.printer = printer if printer else tools.PrintSerializer()

        # Ignore legacy config settings.
        if ',' in binary:
            arr = binary.split(',')
            binary = arr[0]
            self.printer.print(f'ignoring legacy proxy config: {arr[1:]}')

        self.binary = binary

        # There is no check here, if the binary really exists. This happens,
        # when the Proxy process it really started.

    #---------------------------------------------------------------------------
    def print(self, msg):
        if self.printer:
            self.printer.print(msg)


    #---------------------------------------------------------------------------
    def is_running(self):
        return self.process and self.process.is_running()


    #---------------------------------------------------------------------------
    def stop(self):
        if self.is_running():
            self.print('terminating proxy')
            self.process.terminate()

        # cleanup
        self.process = None


    #---------------------------------------------------------------------------
    # Connection is of the form "UART:<dev>" or "TCP:<port".
    def start(self, log_dir, connection, enable_tap = False, print_log = False):

        if self.is_running():
            raise Exception('proxy already running')

        cmd_arr = [self.binary, '-c', connection]
        if enable_tap:
            cmd_arr += ['-t', '1']

        self.print(f'starting Proxy: {" ".join(cmd_arr)}')

        if not self.binary or not os.path.isfile(self.binary):
            raise Exception(f'missing proxy app: {self.binary}')

        self.process = process_tools.ProcessWrapper(
                           cmd_arr,
                           log_file_stdout = os.path.join(log_dir, 'proxy_out.txt'),
                           log_file_stderr = os.path.join(log_dir, 'proxy_err.txt'),
                           printer = self.printer,
                           name = 'Proxy'
                       )

        self.process.start(print_log = print_log)

        # ToDo: We could check the proxy output to ensure it is running- Output
        #       for '-c UART:/dev/ttyUSB2 -t 1' is:
        #
        #           Starting proxy app of type UART with connection param: /dev/ttyUSB2, use_tap:1
        #           Starting Raw Serial
        #           TapChannelCreator() tapfd = 4
        #           TapChannelCreator() tapfd = 5
        #           Starting Raw Serial
