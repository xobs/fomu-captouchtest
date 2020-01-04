#!/usr/bin/env python3
# This variable defines all the external programs that this module
# relies on.  lxbuildenv reads this variable in order to ensure
# the build will finish without exiting due to missing third-party
# programs.
LX_DEPENDENCIES = ["riscv", "icestorm", "yosys", "nextpnr-ice40"]

# Import lxbuildenv to integrate the deps/ directory
import lxbuildenv

# Disable pylint's E1101, which breaks completely on migen
#pylint:disable=E1101

#from migen import *
from migen import Module, Signal, Instance, ClockDomain, If
from migen.fhdl.specials import TSTriple
from migen.fhdl.decorators import ClockDomainsRenamer

from litex.build.lattice.platform import LatticePlatform
from litex.build.generic_platform import Pins, Subsignal
from litex.soc.integration.doc import AutoDoc, ModuleDoc
from litex.soc.integration.soc_core import SoCCore
from litex.soc.cores.cpu import CPUNone
from litex.soc.integration.builder import Builder
from litex.soc.interconnect import wishbone

from litex.soc.cores import up5kspram, spi_flash

from litex_boards.partner.targets.fomu import _CRG

from valentyusb.usbcore import io as usbio
from valentyusb.usbcore.cpu import dummyusb, eptri
from valentyusb.usbcore.endpoint import EndpointType

import lxsocdoc

import argparse
import os

from rtl.fomucaptouch import CapTouchPads

class Platform(LatticePlatform):
    def __init__(self, board=None, toolchain="icestorm"):
        self.board = board
        if board == "evt":
            from litex_boards.partner.platforms.fomu_evt import _io, _connectors
            LatticePlatform.__init__(self, "ice40-up5k-sg48", _io, _connectors, toolchain="icestorm")
            self.spi_size = 16 * 1024 * 1024
            self.spi_dummy = 6
        elif board == "dvt":
            from litex_boards.partner.platforms.fomu_pvt import _io, _connectors
            LatticePlatform.__init__(self, "ice40-up5k-uwg30", _io, _connectors, toolchain="icestorm")
            self.spi_size = 2 * 1024 * 1024
            self.spi_dummy = 6
        elif board == "pvt":
            from litex_boards.partner.platforms.fomu_pvt import _io, _connectors
            LatticePlatform.__init__(self, "ice40-up5k-uwg30", _io, _connectors, toolchain="icestorm")
            self.spi_size = 2 * 1024 * 1024
            self.spi_dummy = 6
        elif board == "hacker":
            from litex_boards.partner.platforms.fomu_hacker import _io, _connectors
            LatticePlatform.__init__(self, "ice40-up5k-uwg30", _io, _connectors, toolchain="icestorm")
            self.spi_size = 2 * 1024 * 1024
            self.spi_dummy = 4
        else:
            raise ValueError("Unrecognized board: {}.  Known values: evt, dvt, pvt, hacker".format(board))

    def create_programmer(self):
        raise ValueError("programming is not supported")


class BaseSoC(SoCCore, AutoDoc):
    """Fomu Bootloader and Base SoC

    Fomu is an FPGA that fits in your USB port.  This reference manual
    documents the basic SoC that runs the bootloader, and that can be
    reused to run your own RISC-V programs.

    This reference manual only describes a particular version of the SoC.
    The register sets described here are guaranteed to be available
    with a given ``major version``, but are not guaranteed to be available on
    any other version.  Naturally, you are free to create your own SoC
    that does not provide these hardware blocks. To see what the version of the
    bitstream you're running, check the ``VERSION`` registers.
    """

    SoCCore.csr_map = {
        "ctrl":           0,  # provided by default (optional)
        "crg":            1,  # user
        "uart_phy":       2,  # provided by default (optional)
        "uart":           3,  # provided by default (optional)
        "identifier_mem": 4,  # provided by default (optional)
        "timer0":         5,  # provided by default (optional)
        "cpu_or_bridge":  8,
        "usb":            9,
        "picorvspi":      10,
        "touch":          11,
        "reboot":         12,
        "rgb":            13,
        "version":        14,
        "lxspi":          15,
        "messible":       16,
    }

    SoCCore.mem_map = {
        "rom":      0x00000000,  # (default shadow @0x80000000)
        "sram":     0x10000000,  # (default shadow @0xa0000000)
        "spiflash": 0x20000000,  # (default shadow @0xa0000000)
        "main_ram": 0x40000000,  # (default shadow @0xc0000000)
        "csr":      0xe0000000,  # (default shadow @0xe0000000)
    }

    interrupt_map = {
        "timer0": 2,
        "usb": 3,
    }
    interrupt_map.update(SoCCore.interrupt_map)

    def __init__(self, platform, boot_source="rand",
                 debug=None, bios_file=None,
                 use_dsp=True, placer="heap", output_dir="build",
                 pnr_seed=0,
                 **kwargs):
        # Disable integrated RAM as we'll add it later
        self.integrated_sram_size = 0

        self.output_dir = output_dir

        clk_freq = int(12e6)
        self.submodules.crg = _CRG(platform)

        SoCCore.__init__(self, platform, clk_freq, integrated_sram_size=0, with_uart=False, **kwargs)

        usb_debug = False
        if debug is not None:
            if debug == "uart":
                from litex.soc.cores.uart import UARTWishboneBridge
                self.submodules.uart_bridge = UARTWishboneBridge(platform.request("serial"), clk_freq, baudrate=115200)
                self.add_wb_master(self.uart_bridge.wishbone)
            elif debug == "usb":
                usb_debug = True
            elif debug == "spi":
                import spibone
                # Add SPI Wishbone bridge
                debug_device = [
                    ("spidebug", 0,
                        Subsignal("mosi", Pins("dbg:0")),
                        Subsignal("miso", Pins("dbg:1")),
                        Subsignal("clk",  Pins("dbg:2")),
                        Subsignal("cs_n", Pins("dbg:3")),
                    )
                ]
                platform.add_extension(debug_device)
                spi_pads = platform.request("spidebug")
                self.submodules.spibone = ClockDomainsRenamer("usb_12")(spibone.SpiWishboneBridge(spi_pads, wires=4))
                self.add_wb_master(self.spibone.wishbone)
            if hasattr(self, "cpu") and not isinstance(self.cpu, CPUNone):
                self.cpu.use_external_variant("rtl/VexRiscv_Fomu_Debug.v")
                os.path.join(output_dir, "gateware")
                self.register_mem("vexriscv_debug", 0xf00f0000, self.cpu.debug_bus, 0x100)
        else:
            if hasattr(self, "cpu") and not isinstance(self.cpu, CPUNone):
                self.cpu.use_external_variant("rtl/VexRiscv_Fomu_Crypto.v")

        # SPRAM- UP5K has single port RAM, might as well use it as SRAM to
        # free up scarce block RAM.
        spram_size = 128*1024
        self.submodules.spram = up5kspram.Up5kSPRAM(size=spram_size)
        self.register_mem("sram", self.mem_map["sram"], self.spram.bus, spram_size)

        # Add USB pads, as well as the appropriate USB controller.  If no CPU is
        # present, use the DummyUsb controller.
        usb_pads = platform.request("usb")
        usb_iobuf = usbio.IoBuf(usb_pads.d_p, usb_pads.d_n, usb_pads.pullup)
        if hasattr(self, "cpu") and not isinstance(self.cpu, CPUNone):
            self.submodules.usb = eptri.TriEndpointInterface(usb_iobuf, debug=usb_debug)
        else:
            self.submodules.usb = dummyusb.DummyUsb(usb_iobuf, debug=usb_debug)

        if usb_debug:
            self.add_wb_master(self.usb.debug_bridge.wishbone)

        # Add GPIO pads for the touch buttons
        platform.add_extension(CapTouchPads.touch_device)
        self.submodules.touch = CapTouchPads(platform.request("touch_pads"))

        # Override default LiteX's yosys/build templates
        assert hasattr(platform.toolchain, "yosys_template")
        assert hasattr(platform.toolchain, "build_template")
        platform.toolchain.yosys_template = [
            "{read_files}",
            "attrmap -tocase keep -imap keep=\"true\" keep=1 -imap keep=\"false\" keep=0 -remove keep=0",
            "synth_ice40 -json {build_name}.json -top {build_name}",
        ]
        platform.toolchain.build_template = [
            "yosys -q -l {build_name}.rpt {build_name}.ys",
            "nextpnr-ice40 --json {build_name}.json --pcf {build_name}.pcf --asc {build_name}.txt \
            --pre-pack {build_name}_pre_pack.py --{architecture} --package {package}",
            "icepack {build_name}.txt {build_name}.bin"
        ]

        # Add "-relut -dffe_min_ce_use 4" to the synth_ice40 command.
        # The "-reult" adds an additional LUT pass to pack more stuff in,
        # and the "-dffe_min_ce_use 4" flag prevents Yosys from generating a
        # Clock Enable signal for a LUT that has fewer than 4 flip-flops.
        # This increases density, and lets us use the FPGA more efficiently.
        platform.toolchain.yosys_template[2] += " -abc9"
        if use_dsp:
            platform.toolchain.yosys_template[2] += " -dsp"

        # Disable final deep-sleep power down so firmware words are loaded
        # onto softcore's address bus.
        platform.toolchain.build_template[2] = "icepack -s {build_name}.txt {build_name}.bin"

        # Allow us to set the nextpnr seed
        platform.toolchain.build_template[1] += " --seed " + str(pnr_seed)

        if placer is not None:
            platform.toolchain.build_template[1] += " --placer {}".format(placer)

    def copy_memory_file(self, src):
        import os
        from shutil import copyfile
        if not os.path.exists(self.output_dir):
            os.mkdir(self.output_dir)
        if not os.path.exists(os.path.join(self.output_dir, "gateware")):
            os.mkdir(os.path.join(self.output_dir, "gateware"))
        copyfile(os.path.join("rtl", src), os.path.join(self.output_dir, "gateware", src))


def main():
    parser = argparse.ArgumentParser(
        description="Build Fomu Captouch Test")
    # parser.add_argument(
    #     "--boot-source", choices=["spi", "rand", "bios"], default="bios",
    #     help="where to have the CPU obtain its executable code from"
    # )
    parser.add_argument(
        "--document-only", default=False, action="store_true",
        help="Don't build gateware or software, only build documentation"
    )
    parser.add_argument(
        "--board", choices=["evt", "dvt", "pvt", "hacker"], default="pvt",
        help="build foboot for a particular hardware board"
    )
    parser.add_argument(
        "--bios", help="use specified file as a BIOS, rather than building one"
    )
    parser.add_argument(
        "--with-debug", help="enable debug support", choices=["usb", "uart", "spi", None]
    )
    parser.add_argument(
        "--no-cpu", help="disable cpu generation for debugging purposes", action="store_true"
    )
    parser.add_argument(
        "--seed", default=0, help="seed to use in nextpnr"
    )
    parser.add_argument(
        "--export-random-rom-file", help="Generate a random ROM file and save it to a file"
    )
    args = parser.parse_args()

    output_dir = 'build'

    compile_software = False
    # if (args.boot_source == "bios" or args.boot_source == "spi") and args.bios is None:
    #     compile_software = True

    # cpu_type = "vexriscv"
    # cpu_variant = "min"
    # if args.with_debug:
    #     cpu_variant = cpu_variant + "+debug"

    # if args.no_cpu:
    cpu_type = None
    cpu_variant = None

    compile_gateware = True
    if args.document_only:
        compile_gateware = False
        compile_software = False

    os.environ["LITEX"] = "1" # Give our Makefile something to look for
    platform = Platform(board=args.board)
    soc = BaseSoC(platform, cpu_type=cpu_type, cpu_variant=cpu_variant,
                            debug="usb",
                            bios_file=args.bios,
                            pnr_seed=int(args.seed),
                            output_dir=output_dir)
    builder = Builder(soc, output_dir=output_dir, csr_csv="build/csr.csv",
                      compile_software=compile_software, compile_gateware=compile_gateware)
    if compile_software:
        builder.software_packages = [
            ("bios", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sw")))
        ]
    vns = builder.build()
    soc.do_exit(vns)
    lxsocdoc.generate_docs(soc, "build/documentation/", project_name="Fomu Captouch Test", author="Sean Cross")
    lxsocdoc.generate_svd(soc, "build/software", vendor="Foosn", name="Fomu")

    print("""Foboot build complete.  Output files:
        {}/gateware/top.bin             Bitstream file.  Load this onto the FPGA for testing.
        {}/gateware/top-multiboot.bin   Multiboot-enabled bitstream file.  Flash this onto FPGA ROM.
        {}/gateware/top.v               Source Verilog file.  Useful for debugging issues.
        {}/software/include/generated/  Directory with header files for API access.
        {}/software/bios/bios.elf       ELF file for debugging bios.
    """.format(output_dir, output_dir, output_dir, output_dir, output_dir))

if __name__ == "__main__":
    main()
