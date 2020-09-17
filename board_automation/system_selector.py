#!/usr/bin/python3

from . import process_tools
from . import board_automation
from . import automation_QEMU


#-------------------------------------------------------------------------------
def get_test_runner(
        log_dir,
        platform,
        system_image,
        proxy_config,
        print_log = False ):

    run_context = board_automation.Run_Context(
                    log_dir,
                    platform,
                    system_image,
                    process_tools.PrintSerializer(),
                    print_log)

    if (platform == 'imx6'):
        return automation_QEMU.QemuProxyRunner(
                        run_context,
                        proxy_config)

    elif (platform == 'zynq7000'):
        return automation_QEMU.QemuProxyRunner(
                        run_context,
                        proxy_config)

    elif (platform == 'rpi3'):
        pytest.fail('implement me: {}'.format(platform))

    else:
        raise Exception('unsupported platform: {}'.format(platform))