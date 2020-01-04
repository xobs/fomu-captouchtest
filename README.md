# Fomu Captouch Test

This repository represents an attempt to create a working captouch implementation for Fomu.
It is meant to allow experimentation with various approaches.

## Usage

1. Ensure you have the Fomu Toolchain installed
2. Run `python captouchtest.py`.  If you have a Hacker board, add `--board hacker`.
3. Write the resulting `build/gateware/top.bin` to a Fomu
4. Interact with the Captouch addresses via the wishbone bridge.

## Testing the bridge

You can load `build/gateware/top.bin` to a Fomu and use the Wishbone bridge.  To do this,
run `wishbone-tool -s wishbone`.  Then, go to the `client` directory, run `make`, and
then run `./test-program`.

This will print out four numbers.  This corresponds to the four touchpads.  Try touching
the pads to see what the value is.
