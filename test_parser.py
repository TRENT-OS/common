import pytest, re, time, logs


#-------------------------------------------------------------------------------
def fail_on_assert(f_out):
    """
    If there is (so far) an assert in the log then fail the test
    """

    failed_fn = logs.find_assert(f_out)
    if failed_fn:
        pytest.fail("Aborted because {} already failed".format(failed_fn))


#-------------------------------------------------------------------------------
def check_test(test_run, timeout, test_fn, test_args=None, single_thread=True):
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
    """

    __tracebackhide__ = True

    f_out = test_run[1]
    failed_fn = logs.find_assert(f_out) if single_thread else None

    # there is no point in using a timeout if we already know of a failure
    (test_ok, test_assert) = logs.check_result_or_assert(
                                f_out,
                                test_fn,
                                test_args,
                                0 if failed_fn else timeout)
    if test_ok:
        return True

    if test_assert:
        pytest.fail(test_assert)
        return False

    if failed_fn:
        pytest.fail("Aborted because {} already failed".format(failed_fn))
        return False

    # check the whole log file again for an assert
    assert_msg = logs.find_assert(f_out)
    if assert_msg:
        pytest.fail("Timed out because {} failed".format(assert_msg))
        return False

    pytest.fail("Timed out but no assertion was found")
    return False
