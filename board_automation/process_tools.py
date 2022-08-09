#!/usr/bin/python3

import sys
import traceback
import os
import signal
import shutil
import subprocess
import time
import datetime

from . import tools


#---------------------------------------------------------------------------
def execute_os_cmd(
        cmd_arr,
        stdout = subprocess.PIPE,
        stderr = subprocess.STDOUT,
        env = None):

    # ret = os.system(cmd)
    # if (0 != ret):
    #     print('ERROR: ret={} for: {}'.format(ret, cmd_arr))
    # return ret

    p = subprocess.Popen(
            cmd_arr,
            env = env,
            stdout = stdout,
            stderr = subprocess.STDOUT)

    while(True):
        # ToDo: we need a readline() with timeout to avoid blocking here
        line = p.stdout.readline()
        if line:
            line = line.decode('utf-8').strip()
            print('[{}] {}'.format(cmd_arr[0], line))

        else:
            ret = p.poll()
            if ret is not None:
                if (0 != ret):
                    print('ERROR: ret={} for: {}'.format(ret, cmd_arr))

                return ret


#===============================================================================
#===============================================================================

class install_abort_handler():

    #---------------------------------------------------------------------------
    def __init__(self, cleanup_handler):
        self.cleanup_handler = cleanup_handler
        signal.signal(signal.SIGINT, self.signal_handler)


    #---------------------------------------------------------------------------
    def signal_handler(self, sig, frame):
        print('... caught abort')

        if self.cleanup_handler:
            self.cleanup_handler()

        sys.exit(0)


#===============================================================================
#===============================================================================

class ProcessWrapper:

    #---------------------------------------------------------------------------
    def __init__(
        self,
        cmd_arr,
        log_file_stdout = None,
        log_file_stderr = None,
        printer = None,
        name = None
    ):

        self.cmd_arr = cmd_arr
        self.name = self.cmd_arr[0] if name is None else name

        self.printer = printer if printer else tools.PrintSerializer()
        self.process = None

        self.log_file_stdout = log_file_stdout
        self.thread_stdout   = None

        self.log_file_stderr = log_file_stderr
        self.thread_sterr    = None


    #---------------------------------------------------------------------------
    # sub-classes may extend this
    def print(self, msg):
        if self.printer:
            self.printer.print(msg)


    #---------------------------------------------------------------------------
    def is_running(self):
        try:

            p = self.process
            return (p is not None) and (p.poll() is None)

        except Exception as e:

            exc_info = sys.exc_info()
            self.print('Exception in is_running() for {}: {}'.format(self, e))
            traceback.print_exception(*exc_info)

        return False


    #---------------------------------------------------------------------------
    def monitor_channel_loop(
        self,
        h_in,
        name,
        print_log = False,
        f_log = None):

        start = datetime.datetime.now()

        while (True):

            if not self.process:
                # seems the process got terminated
                return

            ret = self.process.poll()
            if (ret is not None):
                msg = '{}: termination, code {}'.format(name, ret)
                self.print(msg)
                return

            line = h_in.readline()
            if (len(line) == 0):
                # readline() can have a timeout
                continue

            line_str = line.decode('utf-8')
            line_str = line_str.replace('\b', '<BACKSPACE>')

            if f_log:
                f_log.write(line_str)
                f_log.write(os.linesep)
                f_log.flush() # ensure things are really written

            if print_log:
                delta = datetime.datetime.now() - start;
                # timestamp = datetime.datetime(delta.total_seconds()).strftime("%H%:M:%S.%f")
                # msg = '[{} {}] {}'.format(timestamp[:-3], name, line_str)
                msg = '[{} {}] {}'.format(delta, name, line_str)
                self.print(msg)


    #---------------------------------------------------------------------------
    def monitor_channel(
        self,
        h_in,
        name,
        print_log = False,
        filename = None):

        try:
            if not filename:
                self.monitor_channel_loop(h_in, name, print_log)

            else:
                with open(filename, "w") as f_log:
                    self.monitor_channel_loop(h_in, name, print_log, f_log)

        except Exception as e:
            exc_info = sys.exc_info()
            self.print('Exception for {}: {}'.format(self, e))
            traceback.print_exception(*exc_info)


    #---------------------------------------------------------------------------
    def start(
        self,
        has_stdin = False,
        env = None,
        print_log = False):

        # process must not be running
        assert(self.process is None)

        has_stdout = print_log or (self.log_file_stdout is not None)
        has_stderr = print_log or (self.log_file_stderr is not None)

        self.process = subprocess.Popen(
                            self.cmd_arr,
                            env = None,
                            stdin = subprocess.PIPE if has_stdin else None,
                            stdout = subprocess.PIPE if has_stdout else None,
                            stderr = subprocess.PIPE if has_stderr else None
                       )

        if has_stdout:
            def thread_stdout(thread):
                self.monitor_channel(
                    self.process.stdout,
                    self.name + '/stdout',
                    print_log,
                    self.log_file_stdout)
            tools.run_in_thread(thread_stdout)

        if has_stderr:
            def thread_stderr(thread):
                self.monitor_channel(
                    self.process.stderr,
                    self.name + '/stderr',
                    print_log,
                    self.log_file_stderr)
            tools.run_in_thread(thread_stderr)

        # set up a termination handler, that does the internal cleanup. This
        # is needed when e.g. our parent process is aborted and thus all child
        # processes are terminated. We need to ensure all our monitoring
        # threads also terminate.
        def watch_termination(thread):
            self.process.wait()
            self.terminate()

        tools.run_in_thread(watch_termination)


    #---------------------------------------------------------------------------
    def terminate(self):
        p = self.process
        if p is not None:
            p.terminate()
            self.process = None
