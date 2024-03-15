#!/usr/bin/python3

#
# Copyright (C) 2020-2024, HENSOLDT Cyber GmbH
# 
# SPDX-License-Identifier: GPL-2.0-or-later
#
# For commercial licensing, contact: info.cyber@hensoldt.net
#

from . import tools
from . import board_automation
from . import automation_QEMU
from . import automation_SabreLite
from . import automation_RasPi
from . import automation_RasPi4
from . import automation_zcu102
from . import automation_OdroidC2
from . import automation_jetson_nano_two_gb
from . import automation_jetson_tx2_nx_a206
from . import automation_jetson_xavier_nx_dev_kit
from . import automation_aetina_an110_xnx
from . import automation_HW_CI

#-------------------------------------------------------------------------------
def get_test_runner(run_context):

    # translate generic platform names
    translation_table = {
        'spike': 'spike64',
        'qemu-arm-virt': 'qemu-arm-virt-a53',
        'qemu-riscv-virt': 'qemu-riscv-virt64',
        'zynqmp': 'zynqmp-qemu-xilinx',
    }
    new_plat = translation_table.get(run_context.platform, None)
    if new_plat is not None:
        print(f'translating PLATFORM: {run_context.platform} -> {new_plat}')
        run_context.platform = new_plat

    boards = {
        automation_QEMU: [
            'sabre',
            'zynqmp',
            'zynqmp-qemu-xilinx',
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
            'qemu-riscv-virt64',
        ],
        automation_SabreLite: [
            'sabre-hw',
        ],
        automation_RasPi: [
            'rpi3',
        ],
        automation_RasPi4: [
            'rpi4',
        ],
        automation_zcu102: [
            'migv',
            'zcu102',
        ],
        automation_OdroidC2: [
            'odroidc2',
        ],
        automation_jetson_nano_two_gb: [
            'jetson-nano-2gb-dev-kit'
        ],
        automation_jetson_tx2_nx_a206: [
            'jetson-tx2-nx-a206'
        ],
        automation_jetson_xavier_nx_dev_kit: [
            'jetson-xavier-nx-dev-kit'
        ],
        automation_aetina_an110_xnx: [
            'aetina-an110-xnx'
        ],
        automation_HW_CI: [
            'rpi3-ci',
            'rpi4-ci',
            'odroidc2-ci',
            'jetson-nano-2gb-dev-kit-ci',
        ]
    }

    for (cls, lst) in boards.items():
        assert isinstance(lst, list)
        if run_context.platform in lst:
            generic_runner = board_automation.System_Runner(run_context)
            board_runnner = cls.get_BoardRunner(generic_runner)
            generic_runner.set_board_runner(board_runnner)
            return generic_runner

    raise Exception(f'unsupported platform: {run_context.platform}')
