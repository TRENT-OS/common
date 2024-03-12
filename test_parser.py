#
# Copyright (C) 2020-2024, HENSOLDT Cyber GmbH
# 
# SPDX-License-Identifier: GPL-2.0-or-later
#
# For commercial licensing, contact: info.cyber@hensoldt.net
#

"""
Test parser

Convenience function for parsing test logs.
"""

import re
import pytest
import board_automation


#-------------------------------------------------------------------------------
# This function is deprecated, because resetting a stream with 'f_out.seek(0)'
# works for files only, other stream (e.g. from sockets) may not support this.
# Seems what the callers really want is something that automatically checks
# the log foir asserts. This could be implemented as a extension of the monitor
# from tools.Log_File.start_monitor(), so there is a global list that collects
# the asserts.
def fail_on_assert(f_out):
    """
    If there is (so far) an assert in the log then fail the test
    """

    # Check the whole stream we have to far, thus the timeout is set to 0
    f_out.seek(0)
    log = board_automation.line_reader.Stream_Line_Reader(stream = f_out)
    ret = log.find_matches_in_lines(
            ( re.compile(r'Assertion failed: @(.*)\((.*)\): (.*)'), 0 ) )
    assert_str = ret.match if ret.ok else None
    f_out.seek(0)

    if assert_str:
        pytest.fail(f'Aborted, {assert_str}')


#-------------------------------------------------------------------------------
def check_test(test_runner, timeout, test_fn, test_args=None, single_thread=True, occurrences=1):
    """
    The strategy to check the test results for cases where there is only a
    single test thread (single_thread=True) is as follows:
        1. If there was already a failure, check if test result is still there
           but do not wait for it.
        2. If there was no failure yet, wait for test result or a failure
           specific to the test we are looking at.
        3. If the test result is not found, we may be in any of these
           situations:
            a. The test we are currently checking failed with an assertion
            b. A different test failed with an assertion and thus stopped the
               entire test run
            c. No assertion of any kind was found, so we have a timeout due to
               other reasons
    If there is more than one test thread (single_thread=False), an assertion
    for one test may not block other tests from completing. Therefore we skip
    step (1.) and always wait for the correct test result to appear (or its
    corresponding assertion).
    For any reason the same test may have to run for more than once, either
    in the same thread or in different threads. In this case one can specify the
    amount of occurrences, by default it's 1.
    """

    __tracebackhide__ = True

    generic_assert_re = re.compile(r'Assertion failed: @(.*)\((.*)\): (.*)')

    test_name = test_fn if test_args is None else f'{test_fn}({test_args})'

    result_re = re.compile(fr'!!! {re.escape(test_name)}: OK\n')
    assert_re = re.compile(fr'Assertion failed: @{re.escape(test_name)}: (.*)\n')

    log = test_runner.get_system_log_line_reader()
    # The timeout is used multiple times, so ensure that a relative timeout
    # works against a general deadline and does not restart each time it is
    # used.
    timeout = board_automation.tools.Timeout_Checker(timeout)

    while occurrences > 0:
        occurrences -= 1

        # Check the whole log for an assert. Set timeout for this iteration to 0
        # if there was one, as further check don't need to wait if we already
        # know of a failure.
        failed_fn = None
        iteration_timeout = timeout
        if single_thread:
            log2 = test_runner.get_system_log_line_reader()
            ret = log2.find_matches_in_lines( (generic_assert_re, 0) )
            if ret.ok:
                failed_fn = ret.match
                iteration_timeout = 0

        log.set_timeout(iteration_timeout)

        for line in log:
            if assert_re.search(line):
                pytest.fail(f"Assert for {failed_fn} found")
            if result_re.search(line):
                break
        else: # no break, we read all available lines and found no match
            if failed_fn:
                pytest.fail(f'Aborted because {failed_fn}')
            # check the whole log again for an assert.
            log2 = test_runner.get_system_log_line_reader()
            ret = log2.find_matches_in_lines( (generic_assert_re, 0) )
            if ret.ok:
                pytest.fail(f'Timed out because {ret.match}')

            pytest.fail(f'Timed out but no assertion was found')

#-------------------------------------------------------------------------------
# Only use this function after the test has finished. It matches the whole log.
def check_test_result(test_runner, test_fn, test_args=None):
    string = f"!!! {test_fn}: OK\n"

    generic_assert_re = re.compile(r'Assertion failed: @(.*)\((.*)\): (.*)')

    test_name = test_fn if test_args is None else f'{test_fn}({test_args})'

    result_re = re.compile(fr'!!! {re.escape(test_name)}: OK\n')
    assert_re = re.compile(fr'Assertion failed: @{re.escape(test_name)}: (.*)\n')

    complete_log = test_runner.get_system_log_line_reader().get_read_lines()

    for line in complete_log:
        if assert_re.search(line):
            pytest.fail(f"Assert for {test_fn} found")
        if result_re.search(line):
            return


#-------------------------------------------------------------------------------
# Match a string in the live log.
def find_string_to(test_runner, timeout, string, test_args=None):
    __tracebackhide__ = True

    log = test_runner.get_system_log_line_reader()
    # The timeout is used multiple times, so ensure that a relative timeout
    # works against a general deadline and does not restart each time it is
    # used.
    timeout = board_automation.tools.Timeout_Checker(timeout)

    while 1:
        iteration_timeout = timeout

        log.set_timeout(iteration_timeout)

        for line in log:
            if string in line:
                return
        else: # no break, we read all available lines and found no match
            pytest.fail(f'Timed out but no assertion was found')

#-------------------------------------------------------------------------------
# Use this function only after the test has finished. It matches the whole log.
def find_string(test_runner, timeout, string, test_args=None):
    log = test_runner.get_system_log_line_reader().get_read_lines()
    
    for line in log:
        if string in line:
            return
    pytest.fail(f'String "{string}" not found in log')