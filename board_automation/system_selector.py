#!/usr/bin/python3

from . import tools
from . import board_automation
from . import automation_QEMU
from . import automation_SabreLite
from . import automation_SabreLite_boardSetup
from . import automation_RasPi
from . import automation_RasPi_boardSetup
from . import automation_zcu102
from . import automation_MigV
from . import automation_MigV_boardSetup


#-------------------------------------------------------------------------------
def get_test_runner(run_context):

    # translate generic platform names
    translation_table = {
        'spike': 'spike64',
        'qemu-arm-virt': 'qemu-arm-virt-a53',
        'qemu-riscv-virt': 'qemu-riscv-virt64'
    }
    new_plat = translation_table.get(run_context.platform, None)
    if new_plat is not None:
        print(f'translating PLATFORM: {run_context.platform} -> {new_plat}')
        run_context.platform = new_plat

    if (run_context.platform in [
            'sabre',
            'zynqmp',
            'zynq7000',
            'spike32',
            'spike64',
            'hifive',
            'migv_qemu',
            'qemu-arm-virt-a15',
            'qemu-arm-virt-a53',
            'qemu-arm-virt-a57',
            'qemu-arm-virt-a72',
            'qemu-riscv-virt32',
            'qemu-riscv-virt64']):
        return automation_QEMU.QemuProxyRunner(run_context)

    if (run_context.platform == 'sabre-hw'):
        return automation_SabreLite.BoardRunner(
                        run_context,
                        automation_SabreLite_boardSetup.Board_Setup(
                            run_context.printer))

    if (run_context.platform == 'rpi3'):
        return automation_RasPi.BoardRunner(
                        run_context,
                        automation_RasPi_boardSetup.Board_Setup(
                            run_context.printer))

    if (run_context.platform in [
            'migv',
            'zcu102']):
        return automation_zcu102.BoardRunner(run_context)

    if (platform == 'migv'):
        return automation_MigV.BoardRunner(
                        run_context,
                        automation_MigV_boardSetup.Board_Setup(
                            run_context.printer))

    raise Exception(f'unsupported platform: {run_context.platform}')
