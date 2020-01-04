from migen import Module, TSTriple, Cat, Signal, If
from litex.soc.interconnect.csr import AutoCSR, CSRStatus, CSRStorage, CSRField
from litex.soc.integration.doc import ModuleDoc
from litex.build.generic_platform import Pins, Subsignal

class CapTouchPads(Module, AutoCSR):
    touch_device = [
        ("touch_pads", 0,
            Subsignal("t1", Pins("touch_pins:0")),
            Subsignal("t2", Pins("touch_pins:1")),
            Subsignal("t3", Pins("touch_pins:2")),
            Subsignal("t4", Pins("touch_pins:3")),
        )
    ]
    def __init__(self, pads):
        self.intro = ModuleDoc("""Fomu Touchpads

        Fomu has four single-ended exposed pads on its side.  These pads are designed
        to be connected to some captouch block, or driven in a resistive touch mode
        in order to get simple touchpad support.

        This block simply provides CPU-controlled GPIO support for this block.  It has
        three registers which control the In, Out, and Output Enable functionality of
        each of these pins.
        """)

        cap_signal_size = 8

        touch1 = TSTriple()
        touch2 = TSTriple()
        touch3 = TSTriple()
        touch4 = TSTriple()
        self.specials += touch1.get_tristate(pads.t1)
        self.specials += touch2.get_tristate(pads.t2)
        self.specials += touch3.get_tristate(pads.t3)
        self.specials += touch4.get_tristate(pads.t4)

        self.o      = CSRStorage(4, description="Output values for pads 1-4", fields=[
            CSRField("o1", description="Output value for pad 1"),
            CSRField("o2", description="Output value for pad 2"),
            CSRField("o3", description="Output value for pad 3"),
            CSRField("o4", description="Output value for pad 4"),
        ])
        self.oe     = CSRStorage(4, description="Output enable control for pads 1-4", fields=[
            CSRField("oe1", description="Output Enable value for pad 1"),
            CSRField("oe2", description="Output Enable value for pad 2"),
            CSRField("oe3", description="Output Enable value for pad 3"),
            CSRField("oe4", description="Output Enable value for pad 4"),
        ])
        self.i      = CSRStatus(4, description="Input value for pads 1-4", fields=[
            CSRField("i1", description="Input value for pad 1"),
            CSRField("i2", description="Input value for pad 2"),
            CSRField("i3", description="Input value for pad 3"),
            CSRField("i4", description="Input value for pad 4"),
        ])
        self.capen  = CSRStorage(4, description="Enable captouch for pads 1-4", fields=[
            CSRField("t1", description="Enable captouch for pad 1"),
            CSRField("t2", description="Enable captouch for pad 2"),
            CSRField("t3", description="Enable captouch for pad 3"),
            CSRField("t4", description="Enable captouch for pad 4"),
        ])
        self.cper   = CSRStorage(32, description="Captouch sample period", reset=524288)
        self.c1     = CSRStatus(cap_signal_size, description="Count of events for pad 1")
        self.c2     = CSRStatus(cap_signal_size, description="Count of events for pad 2")
        self.c3     = CSRStatus(cap_signal_size, description="Count of events for pad 3")
        self.c4     = CSRStatus(cap_signal_size, description="Count of events for pad 4")

        cap_count = Signal(self.cper.size)
        cap1_count = Signal(cap_signal_size)
        cap2_count = Signal(cap_signal_size)
        cap3_count = Signal(cap_signal_size)
        cap4_count = Signal(cap_signal_size)

        self.sync += [
            # If any captouch pads are enabled, perform a captouch tick
            If(self.capen.fields.t1 |
               self.capen.fields.t2 |
               self.capen.fields.t3 |
               self.capen.fields.t4,
                If(cap_count,
                    cap_count.eq(cap_count - 1),
                ).Else(
                    cap_count.eq(self.cper.storage),
                    self.c1.status.eq(cap1_count),
                    cap1_count.eq(0),

                    self.c2.status.eq(cap2_count),
                    cap2_count.eq(0),

                    self.c3.status.eq(cap3_count),
                    cap3_count.eq(0),

                    self.c4.status.eq(cap4_count),
                    cap4_count.eq(0),
                ),
            ),
            If(self.capen.fields.t1,
                touch1.o.eq(1),             # Keep the output value high
                If(touch1.oe,               # If OE is enabled, then we just charged up the output
                    touch1.oe.eq(0),        # Turn OE off and let it start to fall
                ).Else(
                    If(~touch1.i,           # If the output value has fallen
                        touch1.oe.eq(1),    # Increment the count and start over
                        cap1_count.eq(cap1_count + 1),
                    )
                )
            ).Else(
                touch1.o.eq(self.o.fields.o1),
                touch1.oe.eq(self.oe.fields.oe1),
                self.i.fields.i1.eq(touch1.i)
            ),

            If(self.capen.fields.t2,
                touch2.o.eq(1),             # Keep the output value high
                If(touch2.oe,               # If OE is enabled, then we just charged up the output
                    touch2.oe.eq(0),        # Turn OE off and let it start to fall
                ).Else(
                    If(~touch2.i,           # If the output value has fallen
                        touch2.oe.eq(1),    # Increment the count and start over
                        cap2_count.eq(cap1_count + 1),
                    )
                )
            ).Else(
                touch2.o.eq(self.o.fields.o2),
                touch2.oe.eq(self.oe.fields.oe2),
                self.i.fields.i2.eq(touch2.i)
            ),

            If(self.capen.fields.t3,
                touch3.o.eq(1),             # Keep the output value high
                If(touch3.oe,               # If OE is enabled, then we just charged up the output
                    touch3.oe.eq(0),        # Turn OE off and let it start to fall
                ).Else(
                    If(~touch3.i,           # If the output value has fallen
                        touch3.oe.eq(1),    # Increment the count and start over
                        cap3_count.eq(cap3_count + 1),
                    )
                )
            ).Else(
                touch3.o.eq(self.o.fields.o3),
                touch3.oe.eq(self.oe.fields.oe3),
                self.i.fields.i3.eq(touch3.i)
            ),

            If(self.capen.fields.t4,
                touch4.o.eq(1),             # Keep the output value high
                If(touch4.oe,               # If OE is enabled, then we just charged up the output
                    touch4.oe.eq(0),        # Turn OE off and let it start to fall
                ).Else(
                    If(~touch4.i,           # If the output value has fallen
                        touch4.oe.eq(1),    # Increment the count and start over
                        cap4_count.eq(cap4_count + 1),
                    )
                )
            ).Else(
                touch4.o.eq(self.o.fields.o4),
                touch4.oe.eq(self.oe.fields.oe4),
                self.i.fields.i4.eq(touch4.i)
            ),
        ]
