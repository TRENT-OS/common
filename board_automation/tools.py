#!/usr/bin/python3

import sys
import traceback
import os
import pathlib
import fcntl
import socket
import selectors
import threading
import time
import datetime
import re


#-------------------------------------------------------------------------------
# implement "@class_or_instancemethod" attribute for methods
class class_or_instance_method(classmethod):

    def __get__(self, instance, type_):

        descr_get = super().__get__ if instance is None \
                    else self.__func__.__get__

        return descr_get(instance, type_)


#-------------------------------------------------------------------------------
def add_subdir_to_sys_path(path, subdir):
    sys.path.append(
        os.path.join(
            str(pathlib.Path(path).parent.absolute()),
            subdir
        )
    )


#-------------------------------------------------------------------------------
def print_files_from_folder(folder):

    filenames = os.listdir(folder)

    for f in filenames:
        fqn = os.path.join(folder, f)
        stat_info = os.lstat(fqn)
        time_str = time.strftime(
                        "%Y-%m-%d %H:%M:%S",
                        time.gmtime(stat_info.st_mtime))

        print('  {:8d}   {}   {}'.format(stat_info.st_size, time_str, f))


#-------------------------------------------------------------------------------
def get_mountpoints():

    def parse_mntpt(line):
        dev, mntpt, _ = line.split(None, 2)
        return dev, mntpt

    with open('/proc/mounts') as f:
        return dict(map(parse_mntpt, f.readlines()))


#-------------------------------------------------------------------------------
def get_mountpoint_for_dev(dev):

    mntpts = get_mountpoints()
    return mntpts.get(dev)


#-------------------------------------------------------------------------------
def get_disk_id_for_dev(dev):
    folder = '/dev/disk/by-id'

    filenames = os.listdir(folder)
    for f in filenames:
        fqn = os.path.join(folder, f)
        if not os.path.islink(fqn): continue

        link = os.readlink(fqn)
        link_fqn = os.path.join(folder,link)
        linked_dev = os.path.abspath(link_fqn)

        if linked_dev == dev:
            return f

    return None


#-------------------------------------------------------------------------------
def get_disk_path_for_dev(dev):

    # for dev, mp in mntpts.items(): print('{} -> {}'.format(dev, mp))

    folder = '/dev/disk/by-path'
    # contains things like
    #   pci-0000:00:14.0-usb-0:4.2.1.2.1:1.0-scsi-0:0:0:0-part1 -> ../../sda1
    #   pci-0000:00:14.0-usb-0:4.2.1.2.1:1.0-scsi-0:0:0:0 -> ../../sda
    #
    # check for pattern: <buf>-usb-<path>-scsi-<path>[-<id>]


    filenames = os.listdir(folder)
    for f in filenames:
        fqn = os.path.join(folder, f)
        if not os.path.islink(fqn): continue

        link = os.readlink(fqn)
        link_fqn = os.path.join(folder,link)
        linked_dev = os.path.abspath(link_fqn)

        if linked_dev == dev:
            return f

    return None


#-------------------------------------------------------------------------------
def find_usb_by_serial(serial):

    base_dir = '/sys/bus/usb/devices'

    print('check {} for serial: {}'.format(base_dir, serial))

    def get_id(dn, id_file):
        file_name = os.path.join(dn, id_file)
        if not os.path.exists(file_name): return None
        with open(file_name) as f:
            return f.read().strip()

    for usbid in os.listdir(base_dir):
        dn = os.path.join(base_dir, usbid)
        if (serial == get_id(dn, 'serial')):
            print('  {}:{} at {}'.format(
                    get_id(dn, 'idVendor'),
                    get_id(dn, 'idProduct'),
                    dn))
            # no break here, serial may not be unique


#-------------------------------------------------------------------------------
# this is just a convenience function wrapping threading.Thread that can be
# used to run a function in a thread. It's use as
#
#   import tools
#   ...
#   def some_method(self, params):
#      ...
#      def my_thread(thread):
#          self.do_something_special(params)
#
#      self.thread = tools.run_in_thread(my_thread)
#
# instead of doing
#
#   import threading
#   ...
#   def some_method(self, params):
#      ...
#      def my_thread():
#          self.do_something_special(params)
#
#
#      self.thread = threading.Thread(target = my_thread)
#      self.thread.start()
#

#===============================================================================
#===============================================================================
class MyThread(threading.Thread):

    #---------------------------------------------------------------------------
    def __init__(self, func, daemon=None):
        super().__init__(daemon=daemon)
        self.func = func


    #---------------------------------------------------------------------------
    def __str__(self):
        return '{}/{}()'.format(self.name, self.func.__name__)


    #---------------------------------------------------------------------------
    def run(self):
        try:
            self.func(self)
        except: # catch really *all* exceptions
            (e_type, e_value, e_tb) = sys.exc_info()
            print('EXCEPTION in thread {}: {}{}'.format(
                self,
                ''.join(traceback.format_exception_only(e_type, e_value)),
                ''.join(traceback.format_tb(e_tb))))


#-------------------------------------------------------------------------------
def run_in_thread(func):
    t = MyThread(func)
    t.start()
    return t

#-------------------------------------------------------------------------------
def run_in_daemon_thread(func):
    t = MyThread(func, daemon=True)
    t.start()
    return t


#===============================================================================
#===============================================================================

class PrintSerializer():

    #---------------------------------------------------------------------------
    def __init__(self):
        self.lock = threading.Lock()


    #---------------------------------------------------------------------------
    def print(self, msg):

        with self.lock:
            # msg = '[{}] {}'.format(
            #         msg,
            #         datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3])
            print(msg)


#===============================================================================
#===============================================================================

class Timeout_Checker(object):

    #---------------------------------------------------------------------------
    # any value less than 0 or None means infinite, the value 0 can be used to
    # indicate "do not block".
    def __init__(self, timeout_sec):

        self.time_end = None

        if (timeout_sec is None) or (timeout_sec < 0):
            timeout_sec = -1
        else:
            self.time_end = time.time() + timeout_sec

        self.timeout_sec = timeout_sec


    #---------------------------------------------------------------------------
    @classmethod
    def infinite(cls):
        return cls(-1)


    #---------------------------------------------------------------------------
    def is_infinite(self):
        return (self.time_end is None)


    #---------------------------------------------------------------------------
    def has_expired(self):
        return (not self.is_infinite()) and (time.time() >= self.time_end)


    #---------------------------------------------------------------------------
    # this returns a value greater or equal zero, negative values indicate that
    # the timeout is infinite
    def get_remaining(self):
        if self.is_infinite():
            return -1

        time_now = time.time()
        if (time_now >= self.time_end):
            return 0

        return self.time_end - time_now


    #---------------------------------------------------------------------------
    def sleep(self, timeout):
        assert( timeout > 0 )

        if not self.is_infinite():

            timeout_remining = self.get_remaining()

            # don't sleep at all if there is no time left
            if (0 == timeout_remining):
                return

            # adapt sleep time to not exceed the remaining time
            timeout = min(timeout, timeout_remining)

        time.sleep(timeout)


#===============================================================================
#===============================================================================

class Log_File(object):

    #---------------------------------------------------------------------------
    def __init__(self, name):
        self.name = name
        self.monitor_thread = None


    #---------------------------------------------------------------------------
    # if the file does not exist, keep checking every 100 ms until the timeout
    # has expired or the checker function says we can stop
    def open_non_blocking(
            self,
            timeout = None,
            newline = None, # use universal newline mode by default
            mode = 'rt', # read-only text file
            checker_func = None ):

        while True:

            if os.path.isfile(self.name):
                f = open(self.name, mode, newline=newline)
                if f:
                    fd = f.fileno()
                    flag = fcntl.fcntl(fd, fcntl.F_GETFL)
                    fcntl.fcntl(fd, fcntl.F_SETFL, flag | os.O_NONBLOCK)

                return f

            if not timeout or timeout.has_expired():
                return None

            if checker_func and not checker_func():
                return None

            # wait and try again. Using 100 ms seems a good trade-off here, so
            # we don't block for too long or cause much CPU load
            timeout.sleep(0.1)


    #---------------------------------------------------------------------------
    def start_monitor(
            self,
            printer,
            timeout = None,
            checker_func = None):

        #-----------------------------------------------------------------------
        def monitoring_thread(thread):
            # time starts ticking now, since the system is running. The file
            # may not be created until any data is written into it, so
            # successfully opening it can take a while.
            start = datetime.datetime.now()
            f_log = self.open_non_blocking(
                        timeout = timeout,
                        checker_func = checker_func)
            if not f_log:
                # we see this when opening the file failed and we've finally
                # reached the timeout or the checker function told us to stop
                raise Exception('monitor failed, could not open: {}'.format(self.name))

            with f_log:
                is_abort = False
                while not is_abort:
                    line = ''
                    while True:
                        # readline() returns a string terminated by "\n" for
                        # every complete line. On timeout (ie. EOF reached),
                        # there is no terminating "\n".
                        line += f_log.readline()
                        if line.endswith('\n'):
                            # Unfortunately, there is a line break bug in some
                            # logs, where "\n\r" (LF+CR) is used instead of
                            # "\r\n" (CR+LF). Universal newline handling only
                            # considers "\r", "\n" and "\r\n" as line break,
                            # thus "\n\r" is taken as two line breaks and we
                            # see a lot of empty lines in the logs
                            break

                        # could not read a complete line, check termination request
                        if checker_func and not checker_func():
                            is_abort = True
                            break

                        # wait and try again. Using 100 ms seems a good
                        # trade-off here, so we don't block for too long or
                        # cause too much CPU load
                        time.sleep(0.1)

                    if (len(line) > 0):
                        printer.print('[{}] {}'.format(
                            datetime.datetime.now() - start,
                            line.strip()))

            # printer.print('[{}] monitor terminated for {}'.format(self, self.name))


        self.monitor_thread = run_in_thread(monitoring_thread)

    #---------------------------------------------------------------------------
    @classmethod
    def do_find_match_in_lines(cls, hLog, regex, timeout = None):

        regex_compiled = re.compile( regex )
        line = ''

        while True:

            # if we've opened the file in non-blocking mode, this is a
            # non-blocking read, ie if we read something not ending with '\n',
            # it means we have reached the end of input
            line += hLog.readline()
            is_timeout = (timeout is None) or timeout.has_expired()
            if (not line.endswith('\n')) and (not is_timeout):
                # sleep 100 ms or what is left from the timeout. We can use any
                # value here, 100 ms seem a good trade-off between blocking and
                # just wasting CPU time.
                timeout.sleep(0.1)

            else:
                mo = regex_compiled.search(line)
                if mo:
                    return mo.group(0)

                if is_timeout:
                    return None

                line = ''


    #---------------------------------------------------------------------------
    @classmethod
    def do_match_sequence(cls, hLog, str_arr, timeout = None):
        for idx, expr in enumerate(str_arr):
            regex = re.escape(expr)
            match = cls.do_find_match_in_lines(hLog, regex, timeout)
            if match is None:
                return (False, idx)

            # we don't support any wildcards for now
            assert(match == expr)

        # done with the sequence, all strings found
        return (True, None)


    #---------------------------------------------------------------------------
    @classmethod
    def do_match_multiple_sequences(cls, hLog, seq_arr, timeout = None):
        for idx, (str_arr, timeout_sec) in enumerate(seq_arr):
            # we already have the first timeout running, for for every
            # further element we set up a new timeout
            if (idx > 0):
                timeout = Timeout_Checker(timeout_sec)

            (ret, idx2) = cls.do_match_sequence(hLog, str_arr, timeout)
            if not ret:
                return (False, idx, idx2)

        # done with the array of sequences
        return (True, None, None)


    #---------------------------------------------------------------------------
    def find_match_in_lines(self, regex, timeout = None):
        hLog = self.open_non_blocking(timeout = timeout)
        if not hLog:
            raise Exception('could not open: {}'.format(self.name))

        with hLog:
            return self.do_find_match_in_lines(hLog, regex, timeout)


    #---------------------------------------------------------------------------
    def match_sequence(self, str_arr, timeout = None):
        hLog = self.open_non_blocking(timeout = timeout)
        if not hLog:
            raise Exception('could not open: {}'.format(self.name))

        with hLog:
            return self.do_match_sequence(hLog, str_arr, timeout)


    #---------------------------------------------------------------------------
    def match_multiple_sequences(self, seq_arr):

        # opening the file counts towards the first sequences timeout
        (expr_array, timeout_sec) = seq_arr[0]
        timeout = Timeout_Checker(timeout_sec)

        hLog = self.open_non_blocking(timeout = timeout)
        if not hLog:
            raise Exception('could not open: {}'.format(self.name))

        with hLog:
            return self.do_match_multiple_sequences(hLog, seq_arr, timeout)
