#!/usr/bin/python3

import os
import fcntl
import socket
import selectors
import threading
import time
import datetime
import re


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
def run_in_thread(func):

    class MyThread(threading.Thread):

        #---------------------------------------------------------------------------
        def run(self):
            func(self)


    t = MyThread()
    t.start()
    return t


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

class Socket_With_Read_Cancellation:

    #---------------------------------------------------------------------------
    def __init__(self, s):

        self.socket = s

        self.do_cancel_recv = False
        self.do_close = False
        self.recv_or_cancel_event = threading.Event()
        self.recv_cancel_done = threading.Event()

        self.sel = selectors.DefaultSelector()

        def cb_read(s, mask):
            e = self.recv_or_cancel_event
            if e is not None:
                e.set()

        self.sel.register(self.socket, selectors.EVENT_READ, cb_read)

        def my_thread(thread):
            while not self.do_cancel_recv:
                # seem unregistering a callback also triggers an event, thus we
                # never get stuck here if we can ensure do_cancel_recv is set
                # to Falso prior to unregistering.
                events = self.sel.select()
                for key, mask in events:
                    callback = key.data
                    callback(key.fileobj, mask)

        self.thread = run_in_thread(my_thread)


    #---------------------------------------------------------------------------
    def get_socket(self):
        return self.socket


    #---------------------------------------------------------------------------
    def cancel_recv(self, timeout = Timeout_Checker.infinite()):
        self.do_cancel_recv = True

        e = self.recv_or_cancel_event
        if e is None:
            return True

        e.set()

        e_timeout = 0 if timeout is None \
                    else None if timeout.is_infinite() \
                    else timeout.get_remaining()

        return self.recv_cancel_done.wait(e_timeout)


    #---------------------------------------------------------------------------
    def recv(self, buffer_size):

        if self.do_cancel_recv:
            return None

        e = self.recv_or_cancel_event
        if e is None:
            return None

        e.wait()

        if not self.do_cancel_recv:
            ret = self.socket.recv(buffer_size)
            if ret:
                return ret
            # seem the socket has been closed, ensure we shut down
            self.do_cancel_recv = True

        # read has been cancelled or socket closed.
        self.recv_or_cancel_event = None
        self.sel.unregister(self.socket)

        if self.do_close:
            self.socket.close()

        self.recv_cancel_done.set()

        return None


    #---------------------------------------------------------------------------
    def send(self, buffer):
        return self.socket.send(buffer)


    #---------------------------------------------------------------------------
    def sendall(self, buffer):
        return self.socket.sendall(buffer)


    #---------------------------------------------------------------------------
    def close(self, timeout = Timeout_Checker.infinite() ):
        self.do_close = True
        return self.cancel_recv(timeout)



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
        def monitoring_thread():
            # time starts ticking now, since the system is running. The file
            # may not be created until any data is writte into it, so
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


        self.monitor_thread = threading.Thread(
                                target = monitoring_thread,
                                args = ()
                              ).start()

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
